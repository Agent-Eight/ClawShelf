"""Installer process tests with isolated tools; no real host or package mutations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Each fake tool records its argv. Node remains real to exercise JSON/path handling.
TOOL = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['CASE_ROOT'])
with (root/'calls').open('a') as f: f.write(json.dumps([name, *args])+'\n')
if name == os.environ.get('FAIL_TOOL'): sys.exit(17)
if name == 'uname': print(os.environ.get('TEST_OS', 'Linux'))
elif name == 'brew': sys.exit(0 if args[0] != 'list' or os.environ.get('SQLITE') else 1)
elif name == 'openclaw':
    if '--help' in args: print('--agent --global --as')
    elif args[1] == 'list': print(json.dumps({'workspaceDir':str(root/'agent space'), 'managedSkillsDir':str(root/'shared space')}))
    elif args[1] == 'install':
        target = root/('shared space' if '--global' in args else 'agent space/skills')/'clawshelf'
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(os.environ['SOURCE_ROOT'], target, ignore=shutil.ignore_patterns('.git', '.venv', '__pycache__', '.clawshelf-runtime'))
        print(f'Installed clawshelf from git -> {target}')
    elif args[1] == 'info':
        target = root/('shared space' if os.environ.get('SHARED') else 'agent space/skills')/'clawshelf'
        print(json.dumps({'filePath':str(target/'SKILL.md'), 'eligible':not bool(os.environ.get('HIDDEN'))}))
elif name == 'uv':
    if args[0] == '--version': print('uv test')
    elif 'verify-install.py' in args[-1]: print('fake smoke passed')
    elif 'python' in args:
        i=args.index('python'); os.execv(sys.executable,[sys.executable,*args[i+1:]])
elif name == 'npm':
    prefix=pathlib.Path(args[args.index('--prefix')+1]); (prefix/'bin').mkdir(parents=True, exist_ok=True)
    qmd=prefix/'bin/qmd'; qmd.write_text('#!/bin/sh\necho "qmd 2.5.3 (test)"\n');qmd.chmod(0o755)
elif name == 'curl':
    target=pathlib.Path(args[args.index('-o')+1])
    target.write_text('#!/bin/sh\nmkdir -p "$UV_INSTALL_DIR"\ncp "$CASE_ROOT/uv-template" "$UV_INSTALL_DIR/uv"\n')
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='clawshelf-installer-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root/'bin'
        self.bin.mkdir()
        for name in ['openclaw', 'npm', 'uv', 'uname', 'brew', 'curl']:
            p=self.bin/name; p.write_text(TOOL); p.chmod(0o755)
        for name in ['node','python3','git']:
            (self.bin/name).symlink_to(shutil.which(name))
        (self.root/'uv-template').write_text(TOOL)
        (self.root/'uv-template').chmod(0o755)
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin',
                        CASE_ROOT=str(self.root), SOURCE_ROOT=str(ROOT),
                        XDG_DATA_HOME=str(self.root/'data space'), TMPDIR=str(self.root))

    def run_install(self, *args, success=True):
        result=subprocess.run(['/bin/bash', str(ROOT/'install.sh'), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
        return result

    def calls(self):
        return [json.loads(line) for line in (self.root/'calls').read_text().splitlines()]

    def test_install_retry_reinstall_and_agent(self):
        self.run_install('--agent','research')
        self.run_install('--agent','research')
        installs=[c for c in self.calls() if c[:3]==['openclaw','skills','install'] and '--help' not in c]
        self.assertEqual(len(installs),1)
        self.assertEqual(installs[0][-2:],['--agent','research'])
        self.assertNotIn('--force',installs[0])
        self.assertEqual(len([c for c in self.calls() if c[0]=='npm']),1)
        self.run_install('--agent','research','--reinstall')
        self.assertTrue(any('--force' in c for c in self.calls()))
        self.assertFalse(any('gateway' in c or 'message' in c for c in self.calls()))

    def test_pipe_entry_and_wsl(self):
        self.env['WSL_DISTRO_NAME']='Ubuntu'
        result=subprocess.run(['/bin/bash','-s','--'],input=(ROOT/'install.sh').read_text(),
                              env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_existing_older_skill_needs_explicit_reinstall(self):
        target=self.root/'agent space/skills/clawshelf'
        target.mkdir(parents=True)
        (target/'SKILL.md').write_text('original user copy')
        result=self.run_install(success=False)
        self.assertIn('--reinstall',result.stderr)
        self.assertEqual((target/'SKILL.md').read_text(),'original user copy')
        self.assertFalse(any(c[:3]==['openclaw','skills','install'] and '--help' not in c for c in self.calls()))

    def test_missing_openclaw(self):
        (self.bin/'openclaw').unlink()
        self.run_install(success=False)
        self.assertFalse(any(c[0]=='npm' for c in self.calls()))

    def test_global(self):
        self.env['SHARED']='1'
        self.run_install('--global')
        self.assertTrue((self.root/'shared space/clawshelf/.clawshelf-runtime').is_file())

    def test_invalid_arguments_do_not_run_tools(self):
        for args in [('--global','--agent','a'),('--agent',),('--unknown',)]:
            self.run_install(*args,success=False)
        self.assertFalse((self.root/'calls').exists())

    def test_missing_brew(self):
        self.env['TEST_OS']='Darwin';(self.bin/'brew').unlink()
        self.run_install(success=False)
        self.assertFalse(any(c[0]=='npm' for c in self.calls()))

    def test_macos_installs_sqlite(self):
        self.env['TEST_OS']='Darwin'
        # Simulate brew's persistent package database after installation.
        p=self.bin/'brew';p.write_text('#!/bin/sh\nif [ "$1" = list ]; then test -e "$CASE_ROOT/sqlite"; else touch "$CASE_ROOT/sqlite"; fi\n');p.chmod(0o755)
        self.run_install()
        self.assertTrue((self.root/'sqlite').exists())

    def test_unsupported_os(self):
        self.env['TEST_OS']='MINGW64_NT';self.run_install(success=False)

    def test_old_node(self):
        (self.bin/'node').unlink();(self.bin/'node').write_text('#!/bin/sh\nexit 1\n');(self.bin/'node').chmod(0o755)
        self.run_install(success=False)

    def test_npm_failure(self):
        self.env['FAIL_TOOL']='npm';r=self.run_install(success=False)
        self.assertIn('initializing Python and QMD',r.stderr)
        self.assertNotIn('ClawShelf 安装完成',r.stdout)

    def test_download_failure(self):
        (self.bin/'uv').unlink();self.env['FAIL_TOOL']='curl';self.run_install(success=False)

    def test_private_uv_reused(self):
        (self.bin/'uv').unlink()
        self.run_install();self.run_install()
        self.assertEqual(len([c for c in self.calls() if c[0]=='curl']),1)

    def test_host_rejection(self):
        p=self.bin/'openclaw';p.write_text(TOOL.replace("elif args[1] == 'install':", "elif args[1] == 'install':\n        print('policy rejected'); sys.exit(17)"))
        r=self.run_install(success=False);self.assertIn('policy rejected',r.stderr)

    def test_hidden_skill_is_not_success(self):
        self.env['HIDDEN']='1';self.run_install(success=False)

    def test_unwritable_data_location(self):
        (self.root/'file').write_text('not a directory')
        self.env['XDG_DATA_HOME']=str(self.root/'file')
        self.run_install(success=False)

    def test_runtime_with_minimal_path_and_custom_xdg(self):
        self.run_install()
        runtime=self.root/'agent space/skills/clawshelf/scripts/run.sh'
        env=dict(self.env, PATH='/usr/bin:/bin', XDG_DATA_HOME=str(self.root/'different'))
        result=subprocess.run(['/bin/bash',str(runtime),'python','-c',
            'import shutil; assert all(shutil.which(t) for t in ["uv","node","qmd","openclaw"])'],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
