#!/usr/bin/env python3
"""Exercise extraction and isolated lexical retrieval without downloading models."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    runtime = Path(__file__).resolve().parent / "run.sh"
    with tempfile.TemporaryDirectory(prefix="clawshelf-install-") as directory:
        root = Path(directory)
        documents = root / "documents"
        documents.mkdir()
        marker = "clawshelfinstallerverification"
        source = documents / "sample.txt"
        source.write_text(f"{marker}: document extraction and retrieval work.\n")
        extracted = subprocess.check_output(
            [sys.executable, str(runtime.parent / "extract-source.py"), str(source)], text=True
        )
        if marker not in json.loads(extracted).get("content", ""):
            raise RuntimeError("Source extraction did not return the expected content")
        (documents / "sample.md").write_text(f"# Installer verification\n\n{marker}\n")
        env = dict(os.environ, QMD_CONFIG_DIR=str(root / "config"),
                   INDEX_PATH=str(root / "index.sqlite"))
        def qmd(*args):
            return subprocess.check_output(["/bin/bash", str(runtime), "qmd", *args], env=env, text=True)
        qmd("collection", "add", str(documents), "--name", "installer-check")
        qmd("update")
        result = qmd("search", marker, "-c", "installer-check", "--json")
        if "sample.md" not in result:
            raise RuntimeError("QMD search did not return the test document")
    print("Extraction and isolated QMD keyword retrieval passed.")


if __name__ == "__main__":
    main()
