<p align="right">
  <a href="README.md">English</a> | <strong>中文</strong>
</p>

# Codex 与 Claude Code Usage

这是基于 [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)
的 fork，在原有命令行工具基础上新增了一个本地网页仪表盘，用来查看本机
Codex 与 Claude Code 用量信息，以及只读的 Codex/OpenAI 相关接口数据。

项目提供一个仪表盘，以及面向 Codex 和 Claude Code 的独立采集器：

- `codex_claude_usage_web.py`：新增的本地深色网页仪表盘，支持自动刷新、中英文切换、
  rate-limit 进度条、每日用量热力图和模型用量图表。
- `codex_usage.py`：上游原始命令行工具，也是 CLI 和网页仪表盘共同使用的核心
  采集与报告实现。
- `claude_usage.py`：独立的 Claude Code 本地 token 采集器，不会把 Claude 逻辑
  写进 `codex_usage.py`。
- `claude_usage_statusline.py`：可选的 Claude Code statusLine 桥接脚本，用于保存
  官方 5 小时和 7 天限额快照。

不需要安装第三方 Python 包。项目只使用 Python 标准库。

> 这不是 OpenAI 或 Codex 的官方工具。它不会兑换额度、购买额度、修改你的账户、
> 修改 Codex 设置，也不会上传本地 transcript。

## 来源与署名

本仓库基于
[MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)。核心实现是上游
`codex_usage.py` CLI，它负责采集并渲染 Codex 用量报告。原始 CLI 版本的项目说明
和完整使用指南保留在 [旧 README](README_OLD.md) 中。

这个 fork 的主要改动是在 `codex_claude_usage_web.py` 中新增一个本地、可自动刷新的浏览器
仪表盘，并补充相关文档。原 CLI 仍然可用，并且仍然是网页仪表盘数据的基础。

上游项目使用 MIT License 分发。复制、修改或再分发本项目时，请保留 `LICENCE`
中的版权声明和许可条款。

## 功能

- 本地网页仪表盘：`http://127.0.0.1:8765`。
- 自动刷新用量视图，也可以手动刷新。
- English / 中文 Chinese 界面切换。
- Online rate-limit 视图固定保留 primary 和 weekly 两个位置；可用窗口显示
  剩余百分比，暂时不可用的窗口显示 `-` 占位。
- reset 倒计时以天、小时、分钟显示。
- 类似 GitHub contributions 的每日本地用量热力图。
- SQLite model counter 堆叠条形图，以及带颜色标识的模型表格。
- 本地 token 总量和最高用量 session。
- Claude Code 5 小时和 Weekly 剩余百分比及重置时间。
- 去重后的 Claude Code 输入、输出、缓存创建和缓存读取 token，并按每日、模型、
  项目和 session 展示。
- 总览页只保留核心限额与模型摘要；详细的 Codex 与 Claude Code 用量面板可从各自的
  模型卡片进入，避免首页过于拥挤。
- 可选的 OpenAI Admin API 用量和成本视图，需要 `OPENAI_ADMIN_KEY`。
- 总览和独立报告中的 Isambard 服务状态；计划维护采用紧凑的可点击入口并在独立本地
  详情页显示，带五分钟本地缓存和上次成功结果回退。
- 原始 CLI 报告和导出功能仍然保留；完整 CLI 指南见
  [README_OLD.md](README_OLD.md)。

## 运行要求

- Python 3.10 或更新版本。
- 本机 Codex 状态目录，通常是 `~/.codex`。
- Claude Code token 统计需要本机 `~/.claude/projects` 日志。
- 如果要查看 reset credits 和在线 usage/profile，需要 Codex home 目录里的
  `auth.json` 登录信息。
- 只有在查看可选的 OpenAI Admin API 用量/成本报告时，才需要 `OPENAI_ADMIN_KEY`。

默认情况下，工具从这里读取 Codex 数据：

```text
Path.home() / ".codex"
```

如果你的 Codex 数据在其他位置，可以设置 `CODEX_HOME`。

## 快速开始：网页仪表盘

在仓库目录中运行：

```sh
python3 codex_claude_usage_web.py
```

然后打开：

```text
http://127.0.0.1:8765
```

在终端中按 `Ctrl-C` 可以停止服务。

如果端口 `8765` 已经被占用，可以换一个端口：

```sh
python3 codex_claude_usage_web.py --port 8766
```

然后打开：

```text
http://127.0.0.1:8766
```

常用选项：

```sh
python3 codex_claude_usage_web.py --refresh 30
python3 codex_claude_usage_web.py --quiet
python3 codex_claude_usage_web.py --host 127.0.0.1 --port 8765
```

仪表盘默认绑定到 `127.0.0.1`，所以它默认只用于本机查看。

## Claude Code 限额采集设置

只要本机存在 Claude Code JSONL，会话 token 统计就能直接显示。5 小时和 7 天订阅
限额需要先安装一次随仓库提供的 statusLine 桥接脚本：

```sh
python3 claude_usage_statusline.py --install
```

然后让 Claude Code 完成一次回复。桥接脚本只会把经过筛选的限额快照写到
`~/.claude/usage-dashboard.json`，不会复制 prompt 或回复内容。如果已经配置了其他
statusLine，安装会停止而不会覆盖；只有确定要替换时才使用 `--force`。

独立脚本也可以直接运行：

```sh
python3 claude_usage.py
python3 claude_usage.py --json --days 30 --top 10
python3 claude_usage_statusline.py --status
python3 claude_usage_statusline.py --uninstall
```

Claude Code 使用非默认目录时设置 `CLAUDE_CONFIG_DIR`；只有需要自定义快照路径时才设置
`CLAUDE_USAGE_SNAPSHOT`。

## Isambard 服务状态与计划维护

在总览中，`Codex Online Rate Limits` 固定显示在第一位，`Isambard Service Status`
显示在第二位。也可以在 `Report` 选择框中选取 `Isambard 服务状态`，只查看这类数据。

Isambard 面板会显示当前服务状态卡片和源数据元信息。面板中的 **计划维护** 是一个可点击
入口，完整维护计划会在本机二级页显示：

```text
http://127.0.0.1:8765/isambard-maintenance
```

普通的自动刷新最多使用五分钟本地缓存，不会反复轮询 Isambard 公开网站。在总览或
`Isambard 服务状态` 报告中点击 dashboard 的 **刷新**，或在维护详情页点击
**刷新源数据**，会立即请求两个公开源页面。如果新请求失败，dashboard 会继续显示上次
成功的结果，并给出提示。

## 原始 CLI

原始命令行工具仍然保留为 `codex_usage.py`，并且仍然是网页仪表盘使用的核心
采集/报告实现。CLI 安装、命令、导出、认证说明和故障排查，请看保留的
[旧 README](README_OLD.md)。

## 报告类型

**总览**展示 Codex 与 Claude Code 的核心限额和模型摘要。在 **Codex Models** 或
**Claude Code Models** 卡片下方点击链接，可进入相应详情视图。Codex 详情包含重置额度、
Codex Profile Statistics、本地总量、每日用量、最高用量 session，以及可选的 Admin API 区域；
Claude Code 详情包含本地总量、每日用量、项目和最高用量 session。

| 报告 | Dashboard/API value | 网络请求 |
| --- | --- | --- |
| 总览 | `report=all` | 是 |
| Codex 用量 | `report=codex-usage` | 是；包含重置额度、本地/在线用量，以及可选的 Admin API 用量/成本 |
| Claude Code 用量 | `report=claude-usage` | 否 |
| Isambard 服务状态 | `report=isambard-status` | 是，公开页面；本地缓存 |

## Dashboard API

网页服务也提供本地 JSON 接口：

```text
GET /
GET /isambard-maintenance
GET /healthz
GET /api/usage
```

示例：

```text
http://127.0.0.1:8765/api/usage?report=codex-usage&top=10&days=30
```

常用 query 参数：

| 参数 | 作用 | 默认值 |
| --- | --- | --- |
| `report` | `all`, `codex-usage`, `claude-usage`，或 `isambard-status` | `all` |
| `top` | 返回多少条排行数据 | `10` |
| `days` | 最近多少天的本地每日窗口 | `30` |
| `warn_days` | reset 即将过期提示窗口 | `7` |
| `bucket_width` | API usage 桶宽：`1d`, `1h`, 或 `1m` | `1d` |
| `limit` | 可选的 API usage bucket 数量限制 | 空 |
| `group_by` | 可选 API usage 分组字段，可重复或用逗号分隔 | 空 |
| `no_costs` | 用 `1`, `true`, 或 `yes` 跳过 API costs 查询 | `false` |
| `isambard_force_refresh` | 用 `1`, `true`, 或 `yes` 跳过 Isambard 缓存 | `false` |

## 截图

<!-- markdownlint-disable MD033 -- HTML is used here so GitHub can render bounded thumbnails that link to the full-size screenshots. -->
<p>
  <a href="img/dashboard/1.png"><img src="img/dashboard/1.png" alt="Codex 与 Claude Code 限额总览" width="220"></a>
  <a href="img/dashboard/2.png"><img src="img/dashboard/2.png" alt="服务状态与模型详情入口总览" width="220"></a>
  <a href="img/dashboard/3.png"><img src="img/dashboard/3.png" alt="Codex 用量详细页" width="220"></a>
  <a href="img/dashboard/4.png"><img src="img/dashboard/4.png" alt="Codex 本地每日用量和重置额度" width="220"></a>
  <a href="img/dashboard/5.png"><img src="img/dashboard/5.png" alt="Claude Code 用量详细页" width="220"></a>
  <a href="img/dashboard/6.png"><img src="img/dashboard/6.png" alt="中文版 Isambard 服务状态" width="220"></a>
</p>
<!-- markdownlint-enable MD033 -->

## 文档

- [README.md](README.md)：英文版 README，也是 GitHub 默认显示的首页。
- [WEB_DASHBOARD.md](WEB_DASHBOARD.md)：本地网页仪表盘的详细说明。
- [README_OLD.md](README_OLD.md)：原 CLI 版本的长文档。

## 隐私与安全

- 本地仪表盘默认只从 `127.0.0.1` 提供服务。
- 本地用量从你机器上的 Codex 文件读取。
- Claude Code token 从 `~/.claude/projects/**/*.jsonl` 读取；累计前会按请求和消息标识
  去除重复的流式记录。
- Claude 限额来自官方 statusLine 本地数据，仪表盘不会读取或复用 Claude OAuth 凭据。
- Reset credits 和在线 usage/profile 报告使用只读的 Codex 后端请求。
- `codex-usage` 中可选的 Admin API 区域使用 OpenAI Admin API 官方接口。
- Isambard 视图读取两个公开状态页面，并只在忽略的本地缓存
  `isambard_status_snapshot.json` 中保存解析后的结果。
- 不要提交 `OPENAI_ADMIN_KEY`、Codex `auth.json`、私有导出报告，或包含敏感账户
  信息的截图。

在线报告使用的 Codex 后端接口未公开文档，未来可能变化。请把输出当作有用的
运行状态信息，而不是正式账单。
