<p align="right">
  <a href="README.md">English</a> | <strong>中文</strong>
</p>

# Codex 与 Claude Code 用量仪表盘

一个在本机运行、无需第三方依赖的综合仪表盘，用同一个网页查看 Codex、
Claude Code 用量以及 Isambard 服务信息。

仪表盘整合订阅限额窗口、本地 token 历史、模型和项目分布、每日热力图、session
排行、可选的 OpenAI Admin API 数据，以及 Isambard 服务状态。程序只使用 Python
标准库，默认仅监听 `127.0.0.1`。

> 本仓库现在作为**独立项目**维护，不再将自己定位为与上游同步的传统 fork。
> 其中，**Codex 用量采集与报告基础派生自
> [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)**；综合网页仪表盘、
> Claude Code 支持、statusLine 桥接、Isambard 集成、中英文界面及相关文档，均为
> 本项目后续实现的功能。

本项目不是 OpenAI、Anthropic、Codex、Claude Code 或 Isambard 的官方工具。

## 页面截图

<!-- markdownlint-disable MD033 -- 使用 HTML 让 GitHub 截图画廊保持紧凑。 -->
<p>
  <a href="img/dashboard/1.png"><img src="img/dashboard/1.png" alt="Codex 与 Claude Code 限额总览" width="220"></a>
  <a href="img/dashboard/2.png"><img src="img/dashboard/2.png" alt="Isambard 状态与模型摘要" width="220"></a>
  <a href="img/dashboard/3.png"><img src="img/dashboard/3.png" alt="Codex 用量详情" width="220"></a>
  <a href="img/dashboard/4.png"><img src="img/dashboard/4.png" alt="Codex 每日用量与重置额度" width="220"></a>
  <a href="img/dashboard/5.png"><img src="img/dashboard/5.png" alt="Claude Code 用量详情" width="220"></a>
  <a href="img/dashboard/6.png"><img src="img/dashboard/6.png" alt="中文版 Isambard 服务状态" width="220"></a>
</p>
<!-- markdownlint-enable MD033 -->

## 项目来源与署名

当前代码的来源边界如下：

| 部分 | 来源 |
| --- | --- |
| `codex_usage.py` 及 Codex 采集、计算和报告基础 | 派生自 [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)，并继续作为独立的 Codex 核心；本项目只加入少量面向整合的调整，例如机器可读的获取时间戳 |
| 网页中显示的 Codex 数据结果 | 由上游派生的 `codex_usage.py` 提供数据，再集成进本项目网页 |
| `codex_claude_usage_web.py` 与综合网页界面 | 本项目实现 |
| `claude_usage.py` 与 `claude_usage_statusline.py` | 本项目独立实现，不向 `codex_usage.py` 写入 Claude 逻辑 |
| `isambard_status.py`、中英文界面、页面布局与整合逻辑 | 本项目实现 |

上游项目采用 MIT License。原作者的版权和许可声明保留在
[LICENCE](LICENCE) 中；上游 CLI 的原始说明保留在
[README_OLD.md](README_OLD.md) 中。

## 功能概览

- Codex 限额、Claude Code 限额、Isambard 状态，以及 Codex/Claude 模型摘要的
  本地综合总览。
- 独立的 Codex 与 Claude Code 详情页面。
- 中英文界面，并在本地记住语言选择。
- 紧凑工具栏，保留报告、语言、本地天数、刷新间隔、自动刷新和手动刷新控件。
- 紧凑卡片标题，在标题区域显示 Codex 重置摘要、在线数据更新时间、Claude 快照
  状态、Isambard 缓存时长和计划维护入口。
- Primary/5 小时和 Weekly/7 天限额条及 reset 倒计时。
- 本地 token 总量、模型占比、每日热力图和最高用量 session。
- Claude Code input、output、cache creation 和 cache read token 统计，并按
  request/message 标识去重。
- Claude Code 模型、项目、session、每日和 subagent JSONL 统计。
- 通过 `OPENAI_ADMIN_KEY` 可选显示 OpenAI 组织用量与成本。
- Isambard 当前服务状态和计划维护，带五分钟缓存及上次成功结果回退。
- 供其他工具读取的本地 JSON API。
- 保留原 Codex CLI 报告和 TXT/JSON/CSV 导出功能。

## 运行要求

- Python 3.10 或更新版本。
- 本机 Codex 状态目录，通常为 `~/.codex`。
- Claude token 历史需要 `~/.claude/projects` 下的本地 Claude Code transcript。
- Codex reset credits 和只读在线 usage/profile 数据需要
  `~/.codex/auth.json` 中的 Codex 登录状态。
- 只有可选的 OpenAI Admin API 区域需要 `OPENAI_ADMIN_KEY`。

无需安装 Python 包或第三方依赖。

## 快速开始

在仓库目录运行：

```sh
python3 codex_claude_usage_web.py
```

然后打开：

```text
http://127.0.0.1:8765
```

在终端按 `Ctrl-C` 停止服务。常用参数：

```sh
python3 codex_claude_usage_web.py --port 8766
python3 codex_claude_usage_web.py --refresh 30
python3 codex_claude_usage_web.py --quiet
python3 codex_claude_usage_web.py --host 127.0.0.1 --port 8765
```

默认监听地址有意限制为本机。改成 `0.0.0.0` 后，局域网内其他设备可能访问到账户
和用量信息，请谨慎使用。

## Claude Code 设置

### 本地 token 历史

本地 token 统计无需执行安装命令。`claude_usage.py` 会读取：

```text
~/.claude/projects/**/*.jsonl
```

程序忽略 prompt、回复正文、工具输入和文件内容。只要 Claude Desktop 的 Code
会话写入同一目录，也会被纳入统计。

### 官方 5 小时和 7 天窗口

要保存 Claude Code 提供给 statusLine 脚本的官方订阅限额，需要注册一次随项目提供的
桥接脚本：

```sh
python3 claude_usage_statusline.py --install
```

兼容的 Claude Code 客户端完成一次回复后，桥接脚本会将经过筛选的快照写入：

```text
~/.claude/usage-dashboard.json
```

快照只包含限额百分比、reset 时间、模型元数据和采集元数据，不保存 prompt 或回复。
如果已经存在其他 statusLine，安装不会覆盖；只有明确需要替换时才使用 `--force`。

常用独立命令：

```sh
python3 claude_usage.py
python3 claude_usage.py --json --days 30 --top 10
python3 claude_usage_statusline.py --status
python3 claude_usage_statusline.py --uninstall
```

> 网页自动刷新只能重新读取已有快照，不能要求 Anthropic 更新快照。Claude Desktop
> 可能会持续写入本地 JSONL，却不调用自定义 statusLine。此时 token 图表会继续更新，
> 但 5 小时/7 天限额快照会逐渐过期。页面会显示 snapshot age 和 stale 状态，避免把
> 旧数据误认为账户实时用量。

## 页面与数据来源

| 页面 | 主要内容 | 网络请求 |
| --- | --- | --- |
| 总览（`all`） | Codex 限额、Claude Code 限额、Isambard 状态和模型摘要 | Codex 只读接口与 Isambard 公开页面；其他为本地数据 |
| Codex 用量（`codex-usage`） | Reset credits、本地 token/模型/每日/session、在线 profile，以及可选 Admin API 数据 | 是 |
| Claude Code 用量（`claude-usage`） | 本地 token、模型、项目、每日、session 和保存的 statusLine 快照 | 否 |
| Isambard 服务状态（`isambard-status`） | 当前服务卡片和计划维护 | 公开页面，本地缓存 |

完整计划维护页面：

```text
http://127.0.0.1:8765/isambard-maintenance
```

普通自动刷新最多复用五分钟 Isambard 缓存；手动刷新会跳过缓存。如果在线请求失败，
页面会保留最近一次成功结果并显示警告。

Isambard 主卡片会把来源元数据保持在紧凑状态：使用缓存时在标题显示缓存时长，并在标题
提供维护窗口数量和完整计划入口。总览工具栏固定请求排行前 10 行；通过 JSON API 调用时，
仍可使用 `top` 参数指定其他数量。

## 本地 JSON API

网页服务提供：

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

| 参数 | 作用 | 默认值 |
| --- | --- | --- |
| `report` | `all`、`codex-usage`、`claude-usage` 或 `isambard-status` | `all` |
| `top` | 排行数据最多返回多少行 | `10` |
| `days` | 最近多少天的本地每日窗口 | `30` |
| `warn_days` | Reset credit 即将过期的提示窗口 | `7` |
| `bucket_width` | Admin API 桶宽：`1d`、`1h` 或 `1m` | `1d` |
| `limit` | 可选的 Admin API bucket 数量限制 | 空 |
| `group_by` | 可选的 Admin API 分组字段，可重复或用逗号分隔 | 空 |
| `no_costs` | 使用 `1`、`true` 或 `yes` 跳过 Admin API cost 请求 | `false` |
| `isambard_force_refresh` | 使用 `1`、`true` 或 `yes` 跳过 Isambard 缓存 | `false` |

## 独立采集器与原 Codex CLI

不启动网页也可以单独运行采集器：

```sh
python3 claude_usage.py
python3 codex_usage.py
python3 codex_usage.py local-usage --top 20 --days 60
python3 codex_usage.py export --report all --format json
```

在交互式终端直接运行 `codex_usage.py` 会打开菜单。完整命令、导出和故障排查说明见
[README_OLD.md](README_OLD.md)。

## 配置项

| 环境变量 | 作用 |
| --- | --- |
| `CODEX_HOME` | 使用 `~/.codex` 以外的 Codex 数据目录 |
| `CLAUDE_CONFIG_DIR` | 使用 `~/.claude` 以外的 Claude Code 数据目录 |
| `CLAUDE_USAGE_SNAPSHOT` | 从其他位置保存/读取 Claude 限额快照 |
| `CLAUDE_USAGE_STALE_SECONDS` | 修改 Claude 快照默认 15 分钟的过期判断阈值 |
| `OPENAI_ADMIN_KEY` | 启用可选的 OpenAI 组织用量与成本请求 |

## 隐私与限制

- 服务默认只监听 `127.0.0.1`。
- 只读取本地 Codex 和 Claude 文件，不修改这些文件。
- Claude 流式重复记录会在累计 token 前去重。
- Claude statusLine 桥接不会读取或复用 Claude OAuth 凭据。
- Codex reset-credit 和在线 profile 请求均为只读。
- OpenAI Admin API 是可选功能，并使用公开文档接口。
- Isambard 数据来自公开状态页，本地只保存解析后的缓存。
- 各采集器独立处理错误，单个来源不可用不会使整个网页停止工作。

上游派生的 Codex 采集器使用了部分未公开的 Codex 订阅接口，这些接口未来可能变化。
所有数值都应视为运行状态参考，而不是正式账单。请勿提交 API key、`auth.json`、私有
导出文件、账户缓存或包含敏感信息的截图。

## 文档

- [README.md](README.md)：英文版，也是 GitHub 默认显示的首页。
- [WEB_DASHBOARD.md](WEB_DASHBOARD.md)：仪表盘行为和数据来源的详细说明。
- [README_OLD.md](README_OLD.md)：上游派生 Codex CLI 的保留文档。

## 许可证

本项目使用 MIT License，详见 [LICENCE](LICENCE)。上游派生的 Codex 实现保留了
MacSteini 的原始版权声明。
