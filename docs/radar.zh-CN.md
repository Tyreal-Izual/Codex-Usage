# Codex Radar 模型评测

[返回快速开始](../README.zh-CN.md)

Radar 默认启用，可通过工具栏复选框暂停或恢复采集。采集器仍在 `codex_radar.py`，
卡片资源位于 `static/radar.js` 和 `static/radar.css`。存在 Banked Resets 卡片时，
Radar 放在它的下方；也支持只启用 Radar 来源。
[查看当前卡片截图](screenshots.md#current-radar-score-cards)。

## 当前基准：RadarBench

本集成按[雷达公开网站](https://codexradar.com/) **2026-10-17** 的 RadarBench
公开汇总 v6 接口更新，并兼容已保存的 v5 快照。原来的综合 IQ、软件工程和视觉推理属于旧基准，不能与新雷达分混用。

- 当前验证目录包含 DeepSWE、Pompeii、TB4、Science 四类共 64 道题。直接读取公开
  汇总接口的 0–150 分，不自行重算。每题取最近三次有效判分，已覆盖题目等权；
  缺失题目不计零，真实的零分仍保留。
- 显示 Astra、6.1 Sol、6 Sol、5.6 Sol、6 Luna、5.6 Luna，共 34 个配置。
  Sol 与 Astra 包含 **ultra**，Luna 最高为 **max**。旧版 30 份样本门槛不适用于新基准。
- 卡片显示“暂定”“覆盖完整”或“待测”、覆盖题数（共 64 题），以及用于计分的记录数
  （每个已覆盖题目最多三份）。
- 面板只展示官网提供的**总雷达分**。每个模型一行，卡片按 ultra → low 排序，Luna
  从 max 开始。分数保留一位小数，下方细条长度为**雷达分 ÷ 150 × 100%**；所有模型
  共用固定满分 150，不按每行最高分重新归一化。
- 真实零分显示 `0.0` 和空条；缺失成绩显示 `—` 和虚线占位。保留覆盖题数、题次与
  状态作为成绩说明。
- 移除历史曲线、模型选择器、费用/耗时视图与分项评分切换。可展开的数据表只列当前
  分数；窄屏自动换为三列或两列卡片。

## 同步与缓存

来源启用且网页服务器运行时，后台每四小时读取一次公开目录及其 34 个配置，逐个请求，
限制超时和响应大小。浏览器刷新只访问已鉴权的 `GET /api/codex-radar` 内存缓存，
不会触发上游抓取。无需浏览器保持打开；休眠或离线会延迟同步。

标题 age 表示距上次成功的**本地同步**经过多久。最近 UTC 判分日单独显示；
最近判分日取自上游每日历史，不代表精确判分时间；历史仍保留在缓存中，但不展示。

只有全部配置通过同一目录、同一题集摘要的校验，才替换缓存。失败时保留上次成功
快照，按 15、30、60、120、最多 240 分钟退避重试。v6 升级期间可回退到已保存的
v5 RadarBench 分数。旧缓存版本启动后立即尝试升级；
旧 IQ 不再展示，包括升级失败的情况。没有有效新版快照时提示数据暂不可用，
仅已成功获取的 RadarBench 快照可用于失败回退。

默认缓存在每用户缓存目录下的 `codex_radar_snapshot.json`，可通过
`CODEX_USAGE_CACHE_DIR` 覆盖目录；其中只含公开评测元数据，不含账户凭据。
关闭来源后停止后续请求，已经进行中的单个请求可能会先完成。

```sh
python3 codex_radar.py                 # 到期才更新，然后输出 JSON
python3 codex_radar.py --force         # 立即刷新磁盘缓存
python3 codex_radar.py --cache /tmp/radar.json
```

如果网页服务使用了 `--cache-dir`，独立刷新命令的 `--cache` 也应指向该目录中的
`codex_radar_snapshot.json`。注意 `--cache` 接收文件路径，`--cache-dir` 接收目录：

```sh
python3 codex_radar.py --cache /tmp/codex-usage-cache/codex_radar_snapshot.json --force
python3 codex_claude_usage_web.py --cache-dir /tmp/codex-usage-cache
```

先停止正在运行的网页服务，再独立强制更新它使用的缓存，最后重启服务，避免两个进程
同时写入同一文件。独立命令不会修改运行中服务的内存数据。代码升级后也需要重启网页服务，
无需另设定时任务。上游目录或响应不兼容时保留最后有效缓存。
分数来自社区评测，不代表账户用量或官方模型评分。
