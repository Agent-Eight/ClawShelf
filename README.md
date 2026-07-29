# ClawShelf

[English](README.en.md) | 简体中文

ClawShelf 能把装有笔记、PDF、电子表格和文章的文件夹变成一个
**主动式研究伙伴**。它不会等你发起搜索，而是持续监控文件夹、处理新材料、
把新证据与你已有的知识连接起来，并随着资料积累主动带来有依据的洞察。

你也可以随时提问。ClawShelf 会建立一个可追溯来源的资料库，跨文件回答问题，
指出矛盾与缺口，并建议值得继续探索的方向。

你的原始文件始终保持不变。ClawShelf 生成的所有内容都会保存在源文件旁独立的
`clawshelf/` 文件夹中。

<p align="center">
  <img src="docs/assets/clawshelf-proactive-hero-zh-CN.svg" alt="一个发生变化的研究文件会与资料架中的既有证据比较，并在 Lark 中生成带来源链接的 P1 级发现" width="100%">
</p>

## ClawShelf 适合谁

当资料已经多到难以全部记住，而你需要的不只是一次性摘要时，ClawShelf 会很有用。
例如：

- 需要比较论文、方法、证据和开放问题的研究人员。
- 需要整理报告、访谈和会议记录的产品与市场团队。
- 需要跟踪决策、实验、基准测试和技术风险的工程师。
- 需要建立有来源支撑的论点并补齐引用的写作者。
- 需要持续观察文件夹中新证据、结论变化或跨来源联系的分析师。

## 它能做什么

- **主动工作。** 激活资料架后，ClawShelf 会监控新增和变更的来源，在后台分析，
  并在发现有价值的跨来源联系时通知你。
- **建立持久的来源资料库。** 每个处理过的文件都会变成可搜索的 Markdown 记录，
  其中包含摘要、证据、局限、源路径和置信度。
- **跨文件回答问题。** 用自然语言搜索整个资料架，获得以原始材料为依据的简洁回答。
- **连接相关证据。** 让 ClawShelf 解释不同来源之间的一致、矛盾、缺口与关系。
- **建议下一步方向。** 主动获得有来源支撑的研究、测试、阅读或写作建议，
  而不必等到你想起来再问。
- **创建交互式概览。** 生成一个独立的本地 HTML 地图，用于浏览来源及其联系。

## 核心功能：主动研究

大多数研究工具都在等待查询。ClawShelf 在设置完成后仍会持续工作。
当来源被新增或修改时，它会自动：

1. 提取并整理新材料。
2. 将新材料与资料架中已有的证据比较。
3. 寻找有意义的联系、矛盾、缺失证据和可能的下一步。
4. 通过激活资料架时使用的 OpenClaw 对话发送更新。

常规入库确认让你了解处理进度；更重要的通知则会呈现可能改变结论或开启新研究方向的
证据联系。每一条联系都会指回来源，让你能够检查证据，而不是相信无法解释的建议。

<p align="center">
  <img src="docs/assets/clawshelf-proactive-loop-zh-CN.svg" alt="ClawShelf 持续监控文件变化、标准化内容、与资料架比较、判定 P1 或 P2 事件，并通过 Lark 发送更新" width="100%">
</p>

## 快速开始

### 1. 安装前置工具

安装 ClawShelf 前，请先安装：

- 有权限读取源文件夹并运行本地命令的 OpenClaw。
- Python 3.11 或更高版本，以及 [`uv`](https://docs.astral.sh/uv/)。
- Node.js 22 或更高版本。
- **QMD**，ClawShelf 用于索引和检索材料的搜索后端。
- macOS 上还需要 QMD 依赖的 Homebrew SQLite。

在 macOS 上，使用以下命令安装所需系统工具和 QMD：

```bash
brew install uv sqlite
npm install -g @tobilu/qmd@2.5.3
```

在其他平台上，请按照
[`uv` 官方说明](https://docs.astral.sh/uv/getting-started/installation/)
进行安装，并在 Node.js 22 或更高版本可用后安装 QMD：

```bash
npm install -g @tobilu/qmd@2.5.3
```

继续之前，请确认前置工具可用：

```bash
uv --version
node --version
qmd --version
qmd status
```

只有在 `qmd --version` 成功后才能继续。如果安装后 shell 仍找不到 `qmd`，
请将 npm 的全局二进制目录加入 `PATH`，重启 shell，然后重新运行检查。

### 2. 从 GitHub 安装 ClawShelf

```bash
openclaw skills install git:https://github.com/Agent-Eight/ClawShelf.git --as clawshelf
openclaw skills info clawshelf
```

这会为当前 OpenClaw agent 安装 ClawShelf。如果希望它在共享技能目录中可用，
请在安装命令中添加 `--global`。

安装后请启动新的 OpenClaw 会话，以便发现该技能及其命令。

如果你已经下载了仓库，也可以直接安装本地文件夹：

```bash
openclaw skills install /path/to/ClawShelf --as clawshelf
```

### 3. 选择源材料文件夹

创建或选择一个包含 ClawShelf 所需材料的本地文件夹：

```text
project-research/
├── meeting-notes.md
├── market-report.pdf
└── budget.xlsx
```

请选择源文件夹本身，而不是其中的 `clawshelf/` 子文件夹。

### 4. 激活资料架

在 OpenClaw 中运行：

```text
/clawshelf use /absolute/path/to/project-research
```

ClawShelf 会：

1. 将该文件夹设为当前会话的资料架。
2. 在不存在时创建资料架工作区。
3. 根据文件夹和你的请求推断初始研究计划。
4. 报告等待处理的文件。
5. 开始主动监控新增和变更的文件。

初始处理会在后台继续进行。ClawShelf 会显示简洁的状态更新，并可能请你确认或调整
推断出的研究计划。之后可以让资料架持续运行：内容变化时，ClawShelf 会处理变化，
并把相关发现带回当前对话。

### 5. 提出第一个问题

使用斜杠命令：

```text
/clawshelf search "哪些证据支持主要建议？"
```

也可以直接用自然语言提问：

```text
比较这个资料架中的报告。总结它们的一致之处、冲突之处，以及仍然缺失的证据。
```

## 日常使用

| 你想做什么 | 示例 |
| --- | --- |
| 跨来源搜索 | `/clawshelf search "关于流动性风险的证据"` |
| 解释主题或主张 | `/clawshelf explain "拥挤交易"` |
| 创建综合简报 | `/clawshelf brief "下一步应该调查什么？"` |
| 生成有来源支撑的想法 | `/clawshelf ideas` |
| 文件变更后刷新 | `/clawshelf refresh` |
| 创建交互式地图 | `/clawshelf overview` |
| 列出已索引来源 | `/clawshelf sources` |
| 检查资料架健康状态 | `/clawshelf status` |
| 显示当前文件夹 | `/clawshelf pwd` |
| 列出已知资料架 | `/clawshelf folders` |

你也可以直接描述想要的结果。例如：

- “查找关于客户留存的矛盾。”
- “添加最新报告后发生了什么变化？”
- “哪些主张拥有最强的证据？”
- “把这些论文整理成文献综述简报。”
- “建议最有前景的下一步研究方向。”

大多数命令都接受可选的文件夹参数。运行 `/clawshelf use` 后，
在该会话剩余时间里通常可以省略文件夹。

## 文件夹发生变化时

这正是 ClawShelf 主动能力发挥作用的地方。激活资料架会启动后台监控器。
当你新增或修改受支持的来源时，ClawShelf 会自动处理它，与已有资料架比较，并可发送：

- 一条简短确认，说明来源已完成入库。
- 当新材料形成有价值且有证据支撑的联系、张力或研究方向时，发送更丰富的更新。

两类更新默认都已启用。高级用户可以把常规入库更新保留在资料架中而不接收通知；
通知设置见[完整命令参考](references/commands.md)。

需要立即检查变化时，运行 `/clawshelf refresh`。如果 ClawShelf 报告资料架不完整或
已损坏，请运行 `/clawshelf repair`。

## 支持的来源

ClawShelf 内置支持提取：

| 来源 | 说明 |
| --- | --- |
| Markdown | `.md` 文件 |
| 纯文本 | `.txt` 文件 |
| PDF | 文本会被转换为按章节组织的 Markdown |
| Excel 工作簿 | `.xlsx` 文件，包括单独的工作表 |
| 网页 | 仅处理你明确提供的 URL |

其他可读取的本地文件也可能通过当前 agent 的文件读取工具工作。
ClawShelf 会跳过无法读取的文件，而不会根据文件名猜测其内容。

## ClawShelf 会创建什么

所有生成内容都保存在 `<your-folder>/clawshelf/` 下：

```text
project-research/
├── meeting-notes.md
├── market-report.pdf
├── budget.xlsx
└── clawshelf/
    ├── normalized/
    ├── clawshelf-metadata.md
    ├── clawshelf-brief.md
    └── clawshelf-overview.html
```

| 输出 | 用途 |
| --- | --- |
| `normalized/` | 每个已处理来源对应一份可追溯来源的 Markdown 记录 |
| `clawshelf-metadata.md` | 来源清单、主题、覆盖范围、主张和置信度 |
| `clawshelf-brief.md` | 可选的综合、矛盾、缺口、想法和下一步方向 |
| `clawshelf-overview.html` | 由 `/clawshelf overview` 生成的可选交互式地图 |

只有在综合有价值或被明确请求时才会创建简报。概览也只会在你请求时生成，
它在本地打开，不需要 Web 服务器或互联网连接。

## 语言与通知

ClawShelf 支持英文和中文。默认的 `auto` 模式会跟随你最新一条消息的语言。

```text
/clawshelf language en
/clawshelf language zh
/clawshelf language auto
```

也可以添加 `--lang en`、`--lang zh` 或 `--lang auto`，覆盖单次命令的语言。

后台更新会通过你激活资料架时所在的 OpenClaw agent 和对话发送。
ClawShelf 会保存路由信息，但绝不会在资料架中保存服务商密码、API 密钥或访问令牌。

## 隐私与安全

<p align="center">
  <img src="docs/assets/clawshelf-traceable-local-first-zh-CN.svg" alt="只读原始文件会在独立的 clawshelf 文件夹中形成可追溯来源的记录，Lark 通知会链接到具名证据" width="100%">
</p>

- 源文件是只读的；ClawShelf 不会编辑、重命名、移动或删除它们。
- 生成文件只会写入源文件夹中的 `clawshelf/` 目录。
- URL 提取只获取你明确提供的页面，不会抓取其中的链接。
- 仅含本地资料的集合可以始终留在本地。只有用户提供的 URL 和当前 agent 使用的服务
  需要网络访问。
- 回答和建议会标明支撑来源，并区分证据与推测。

ClawShelf 可以辅助研究和决策，但不能替代专业的法律、医疗或财务建议，
也不应自主做出高风险决策。

## 已知限制

- 纯图片或重度扫描的 PDF 可能需要外部 OCR，尤其是在脚本不受支持或扫描质量较差时。
- 受密码保护、已损坏或格式不受支持的文件可能会被跳过。
- 电子表格提取会读取工作簿内容，但不会复现复杂的 Excel 交互行为。
- 网页提取不会登录、绕过付费墙或跟随链接。
- 在重要场景中使用前，应根据引用来源核查生成的摘要和想法。
- 其他 agent harness 也可能使用 ClawShelf，但安装、命令发现和本地文件权限会因
  harness 而异。

## 故障排除

### 安装后找不到 ClawShelf

启动新的 OpenClaw 会话，然后验证安装：

```bash
openclaw skills info clawshelf
openclaw skills check
```

### 缺少必需工具

确认已安装 `uv`、Node.js 22 或更高版本，以及 QMD：

```bash
uv --version
node --version
qmd --version
qmd status
```

如果缺少 QMD，请安装兼容版本：

```bash
# 仅 macOS：先安装 QMD 的 SQLite 依赖
brew install sqlite

# 所有平台
npm install -g @tobilu/qmd@2.5.3
```

如果仍找不到 `qmd`，请将 npm 的全局二进制目录添加到 `PATH` 并重启 shell。

### ClawShelf 使用了错误的文件夹

重新选择准确的源文件夹：

```text
/clawshelf use /absolute/path/to/the/source-folder
```

使用 `/clawshelf pwd` 确认当前资料架，或用 `/clawshelf folders` 查看已知资料架。

### 搜索结果中缺少文件

依次运行 `/clawshelf status` 和 `/clawshelf refresh`。检查文件格式是否受支持，
以及 OpenClaw 是否有权限读取。如果状态报告资料架不完整，请运行
`/clawshelf repair`。

### 无法从聊天中打开交互式概览

部分聊天渠道会阻止本地 `file://` 链接。请在拥有该资料架的计算机上直接打开报告的
`clawshelf-overview.html` 路径，或让 agent 附加该 HTML 文件。

## 文档

- [完整命令参考](references/commands.md)
- [架构与技能设计](docs/skill-design.md)
- [与其他 agent harness 的兼容性](references/harness-compatibility.md)
- [想法生成方法](docs/idea-generation-method.md)
- [发布历史](CHANGELOG.md)
- [安全与负责任披露](SECURITY.md)

## 许可证

Copyright 2026 ClawShelf。

本项目基于 [MIT License](LICENSE) 授权。第三方声明见 [NOTICE](NOTICE)。
