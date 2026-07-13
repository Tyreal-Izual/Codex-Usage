# Codex Usage Local Web Dashboard

这个文档记录本仓库新增的本地网页仪表盘。原来的 `codex_usage.py`
命令行工具保持不变；网页版本是新增的 `codex_usage_web.py`，复用原 CLI
里的采集逻辑。

## 这次新增了什么

- 新增 `codex_usage_web.py`，启动一个本机可看的 HTTP 网页服务。
- 默认只监听 `127.0.0.1`，避免把用量数据暴露到局域网。
- 不需要额外安装第三方 Python 包，只使用标准库和原项目代码。
- 页面会按设定间隔自动刷新，也可以手动点击刷新。
- 新增深色背景界面。
- 新增 English / 中文 Chinese 语言切换，并记住上次选择。
- `Online rate limits` 放在页面最上方。
- `Online rate limits` 显示 primary / weekly 还剩多少百分比，而不是已使用多少。
- reset 倒计时使用天、小时、分钟格式，例如 `6 days 3 hr 12 min`
  或 `6 天 3 小时 12 分钟`。
- 移除了顶部那组概览小方框，让页面更紧凑。
- `Profile statistics` 和 `Daily local usage` 放在同一行，并保持卡片高度对齐。
- `Daily local usage` 改成类似 GitHub contributions 的格子热力图。
- 只保留 `SQLite model counters`，移除了重复的
  `Models in session metadata`。
- `SQLite model counters` 顶部使用堆叠条形图展示不同模型 token 占比。
- `SQLite model counters` 表格增加颜色标识和 `Share` 百分比列。
- `Online rate limits` 详情区域改成 4 列，在小屏幕上会自动变成 2 列或 1 列。
- 新增 Isambard 服务状态报告，也会显示在总览中；计划维护是状态区域内的可点击入口，
  会在独立的本地详情页展示。自动刷新会复用五分钟本地缓存，抓取失败时会显示上次成功结果。

## 运行方法

在仓库目录里运行：

```sh
python3 codex_usage_web.py
```

然后打开：

```text
http://127.0.0.1:8765
```

终端里按 `Ctrl-C` 可以停止服务。

如果看到 `OSError: [Errno 48] Address already in use`，说明这个端口已经被占用。
最简单的处理方式是换一个端口：

```sh
python3 codex_usage_web.py --port 8766
```

然后打开：

```text
http://127.0.0.1:8766
```

## 常用参数

换端口：

```sh
python3 codex_usage_web.py --port 8766
```

调整浏览器默认刷新间隔，单位是秒：

```sh
python3 codex_usage_web.py --refresh 30
```

隐藏每次请求的访问日志：

```sh
python3 codex_usage_web.py --quiet
```

修改监听地址：

```sh
python3 codex_usage_web.py --host 127.0.0.1
```

默认 host 是 `127.0.0.1`。如果改成 `0.0.0.0`，局域网内其他设备也可能访问到
这个页面，请谨慎使用。

## 页面控件

页面顶部提供这些控件：

| 控件 | 作用 |
| --- | --- |
| `Report` | 选择总览、本地用量、重置额度、在线用量、OpenAI API 用量，或 `Isambard 服务状态` |
| `Language` | 在 English 和 中文 Chinese 之间切换 |
| `Top rows` | 控制排行榜或表格最多显示多少行 |
| `Local days` | 控制本地每日用量热力图和每日数据窗口 |
| `Refresh sec` | 控制自动刷新间隔 |
| `Auto refresh` | 开启或关闭自动刷新 |
| `Refresh` | 立即手动刷新一次 |

## Isambard 服务状态与计划维护

总览固定把 `Online rate limits` 放在第一位、`Isambard service status` 放在第二位。
计划维护入口会打开二级页：

```text
http://127.0.0.1:8765/isambard-maintenance
```

二级页展示完整维护表，并可用 **刷新源数据** 跳过缓存立即抓取。

## 页面结构

当前总览页面主要包含：

| 区域 | 说明 |
| --- | --- |
| `Online rate limits` | 在线 primary / weekly 限制，显示剩余百分比、reset 时间和账号状态 |
| `Isambard service status` | 公开 Isambard 服务状态、抓取时间与缓存状态；计划维护入口会打开二级详情页 |
| `Reset credits` | 本地可读的 reset credits 信息 |
| `Local token totals` | 从本地 session 文件统计出的 token 总量 |
| `SQLite model counters` | 从本地 thread 数据库按模型聚合，包含堆叠条形图、颜色标识和占比 |
| `Profile statistics` | 在线 profile 统计信息 |
| `Daily local usage` | 类似 GitHub contributions 的本地每日用量热力图 |
| `Top sessions` | 本地 token 计数最高的 session 文件 |
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
| `report` | `all`, `resets`, `local-usage`, `online-usage`, `api-usage`, `isambard-status` | `all` |
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
http://127.0.0.1:8765/api/usage?report=local-usage&top=10&days=30
```

## 数据来源

- 本地用量来自当前配置的 Codex home 目录。
- reset credits 和 online usage 复用原 CLI 的只读网络请求。
- OpenAI Admin API 用量和成本需要设置 `OPENAI_ADMIN_KEY`。
- Isambard 状态从两个公开页面读取，解析后的结果保存在已忽略的
  `isambard_status_snapshot.json` 缓存文件中。
- 网页服务只负责展示和轮询，不会写入 Codex session、thread 或 profile 数据。
