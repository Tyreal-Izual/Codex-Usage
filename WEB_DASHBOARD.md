# Codex & Claude Code Local Web Dashboard

这个文档记录本仓库新增的本地网页仪表盘。原来的 `codex_usage.py`
命令行工具保持不变；Claude Code 采集放在独立的 `claude_usage.py` 和
`claude_usage_statusline.py` 中，网页版本 `codex_claude_usage_web.py` 合并展示两类数据。

## 这次新增了什么

- 新增 `codex_claude_usage_web.py`，启动一个本机可看的 HTTP 网页服务。
- 默认只监听 `127.0.0.1`，避免把用量数据暴露到局域网。
- 不需要额外安装第三方 Python 包，只使用标准库和原项目代码。
- 页面会按设定间隔自动刷新，也可以手动点击刷新。
- 新增深色背景界面。
- 新增 English / 中文 Chinese 语言切换，并记住上次选择。
- `Codex Online Rate Limits` 放在页面最上方。
- `Codex Online Rate Limits` 显示 primary / weekly 还剩多少百分比，而不是已使用多少。
- `Codex Online Rate Limits` 始终保留 primary 和 weekly 两个窗口的位置。后端暂时
  取消其中一个窗口时，该位置及对应的 reset 倒计时会显示 `-` 占位；另一个
  窗口仍显示实际数据。例如暂时没有 5h 限制但仍有 weekly 限制时，左侧
  primary 保留占位，右侧 weekly 显示 weekly 数据。
- reset 倒计时使用天、小时、分钟格式，例如 `6 days 3 hr 12 min`
  或 `6 天 3 小时 12 分钟`。
- 移除了顶部那组概览小方框，让页面更紧凑。
- `Codex Profile Statistics` 和 `Codex Daily Local Usage` 放在同一行，并保持卡片高度对齐。
- `Codex Daily Local Usage` 改成类似 GitHub contributions 的格子热力图。
- 只保留 `Codex Models`，移除了重复的
  `Models in session metadata`。
- `Codex Models` 顶部使用堆叠条形图展示不同模型 token 占比。
- `Codex Models` 表格增加颜色标识和 `Share` 百分比列。
- `Codex Online Rate Limits` 详情区域改成 4 列，在小屏幕上会自动变成 2 列或 1 列。
- 新增 Isambard 服务状态报告，也会显示在总览中：当前服务状态紧凑显示；计划维护
  是状态区域内的可点击入口，会在独立的本地详情页展示。正常自动刷新会复用五分钟
  本地缓存，手动点击刷新会请求公开状态页面。抓取失败时会显示上次成功结果。
- 新增 Claude Code 独立报告和总览区域：5 小时/7 天剩余额度、本地 token 总量、
  每日热力图、模型、项目和最高用量 session。
- Claude JSONL 中同一响应可能重复出现，统计时按 `requestId + message.id` 去重，
  并递归包含 subagent JSONL。

## 运行方法

在仓库目录里运行：

```sh
python3 codex_claude_usage_web.py
```

然后打开：

```text
http://127.0.0.1:8765
```

终端里按 `Ctrl-C` 可以停止服务。

如果看到 `OSError: [Errno 48] Address already in use`，说明这个端口已经被占用。
最简单的处理方式是换一个端口：

```sh
python3 codex_claude_usage_web.py --port 8766
```

然后打开：

```text
http://127.0.0.1:8766
```

## 常用参数

换端口：

```sh
python3 codex_claude_usage_web.py --port 8766
```

调整浏览器默认刷新间隔，单位是秒：

```sh
python3 codex_claude_usage_web.py --refresh 30
```

隐藏每次请求的访问日志：

```sh
python3 codex_claude_usage_web.py --quiet
```

修改监听地址：

```sh
python3 codex_claude_usage_web.py --host 127.0.0.1
```

默认 host 是 `127.0.0.1`。如果改成 `0.0.0.0`，局域网内其他设备也可能访问到
这个页面，请谨慎使用。

## 页面控件

页面顶部提供这些控件：

| 控件 | 作用 |
| --- | --- |
| `Report` | 选择总览、Codex 用量、Claude Code 用量，或 `Isambard 服务状态`；Codex 用量包含重置额度、本地/在线用量和可选的 Admin API 用量/成本 |
| `Language` | 在 English 和 中文 Chinese 之间切换 |
| `Top Rows` | 控制排行榜或表格最多显示多少行 |
| `Local Days` | 控制本地每日用量热力图和每日数据窗口 |
| `Refresh Seconds` | 控制自动刷新间隔 |
| `Auto Refresh` | 开启或关闭自动刷新 |
| `Refresh` | 立即手动刷新一次 |

## Isambard 服务状态与计划维护

总览的固定顺序是 `Codex Online Rate Limits` 在第一位、`Isambard Service Status` 在第二位。
Isambard 面板顶部会显示抓取时间、数据来源、缓存时长（如适用）和可点击的 **计划维护**
入口；入口会打开：

```text
http://127.0.0.1:8765/isambard-maintenance
```

该二级页展示完整维护表，提供返回 dashboard 的链接和 **刷新源数据** 按钮。它与主页面
使用同一份 Isambard 缓存：普通自动刷新最多复用五分钟结果，主页面的 **刷新** 和二级页的
**刷新源数据** 会跳过缓存并立即抓取。抓取失败时，若存在上次成功数据，页面会保留该数据
并显示失败提示。

## 页面结构

当前总览页面主要包含：

| 区域 | 说明 |
| --- | --- |
| `Codex Online Rate Limits` | 固定显示在线 primary / weekly 两个位置；可用窗口显示剩余百分比和 reset 时间，不可用窗口以 `-` 占位，同时显示账号状态 |
| `Claude Code Rate Limits` | statusLine 快照中的 5 小时/7 天剩余百分比、重置时间、快照年龄和安装状态 |
| `Claude Code Local Token Totals` | 去重后的输入、输出、缓存创建、缓存读取和总 token |
| `Claude Code Models` / `Claude Code Projects` / `Claude Code Daily Usage` / `Claude Code Top Sessions` | Claude 本地 JSONL 的模型、项目、每日和 session 排行 |
| `Isambard Service Status` | 公开 Isambard 服务状态、抓取时间与缓存状态；计划维护入口会打开二级详情页 |
| `Codex Reset Credits` | 本地可读的 reset credits 信息 |
| `Codex Local Token Totals` | 从本地 session 文件统计出的 token 总量 |
| `Codex Models` | 从本地 thread 数据库按模型聚合，包含堆叠条形图、颜色标识和占比 |
| `Codex Profile Statistics` | 在线 profile 统计信息 |
| `Codex Daily Local Usage` | 类似 GitHub contributions 的本地每日用量热力图 |
| `Codex Top Sessions` | 本地 token 计数最高的 session 文件 |
| `Admin API status` | 设置 `OPENAI_ADMIN_KEY` 后展示 OpenAI Admin API 用量和成本 |

如果某一类数据读取失败，页面会继续展示其他可用区域，并在顶部提示失败原因。

## 本地接口

网页入口：

```text
GET /
GET /index.html
GET /isambard-maintenance
```

健康检查：

```text
GET /healthz
```

JSON 数据接口：

```text
GET /api/usage
```

常用 query 参数：

| 参数 | 作用 | 默认值 |
| --- | --- | --- |
| `report` | `all`, `codex-usage`, `claude-usage`, `isambard-status` | `all` |
| `top` | 排行榜或表格最多返回多少行 | `10` |
| `days` | 本地每日数据窗口 | `30` |
| `warn_days` | reset 过期提示窗口 | `7` |
| `bucket_width` | API usage 的桶宽，可选 `1d`, `1h`, `1m` | `1d` |
| `limit` | API usage 返回条数限制 | 空 |
| `group_by` | API usage 分组字段，可重复或用逗号分隔 | 空 |
| `no_costs` | 是否跳过 API costs 查询，可用 `1`, `true`, `yes` | `false` |
| `isambard_force_refresh` | 是否跳过 Isambard 五分钟缓存，可用 `1`, `true`, `yes` | `false` |

示例：

```text
http://127.0.0.1:8765/api/usage?report=codex-usage&top=10&days=30
```

## 数据来源

- 本地用量来自当前配置的 Codex home 目录。
- Claude Code token 来自 `CLAUDE_CONFIG_DIR`（默认 `~/.claude`）下的
  `projects/**/*.jsonl`，仅读取 usage、model、timestamp、session 和 cwd 元数据。
- Claude 5 小时和 7 天限额来自 `claude_usage_statusline.py` 保存的官方 statusLine
  字段。首次运行 `python3 claude_usage_statusline.py --install` 后，需让 Claude Code
  完成一次回复才会生成快照。
- reset credits 和 online usage 复用原 CLI 的只读网络请求。
- OpenAI Admin API 用量和成本需要设置 `OPENAI_ADMIN_KEY`。
- Isambard 状态从两个公开页面读取。解析后的结果只保存在本地、且已忽略的
  `isambard_status_snapshot.json` 缓存文件中。
- 网页服务只负责展示和轮询，不会写入 Codex session、thread 或 profile 数据。
