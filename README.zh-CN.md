<p align="right"><a href="README.md">English</a> | <strong>中文</strong></p>

# Codex 与 Claude Code 用量仪表盘

在本地查看订阅限额、token 历史、模型分布和会话统计。
**Python 3.10+ · 无第三方依赖 · 一条命令启动。**
Codex 与 Claude Code 可分别使用，Isambard 服务状态和 Codex Radar 评测为可选来源。

## 快速开始

```sh
git clone https://github.com/Tyreal-Izual/Codex-Usage.git
cd Codex-Usage
python3 codex_claude_usage_web.py
```

打开终端打印的私有访问链接，按 `Ctrl-C` 停止服务。
Windows 可将 `python3` 替换为 `py -3`，确保版本为 Python 3.10 或以上。
基础面板无需 `pip`、Node.js、构建步骤或 API key。

默认 `--sources auto` 在启动时检测本地 Codex／Claude，同时启用服务状态和评测来源。
工具栏中的 **Isambard Status** 和 **Codex Radar** 默认勾选，可随时关闭或重新开启对应来源。

| 使用场景 | 所需条件 |
| --- | --- |
| 只用 Codex | 本地 `~/.codex` 数据；在线限额需要登录 Codex |
| 只用 Claude Code | 本地 `~/.claude/projects` 日志；限额捕获按下方可选步骤设置 |
| 两者都用 | 各自的数据目录；每个来源独立工作 |
| Isambard Status／Codex Radar | 默认勾选，可在工具栏直接切换 |

```sh
python3 codex_claude_usage_web.py --sources codex --default-report codex-usage
python3 codex_claude_usage_web.py --sources claude --default-report claude-usage
python3 codex_claude_usage_web.py --sources all
python3 codex_claude_usage_web.py --check
```

`--check` 输出路径、配置检测结果和快照是否存在，不读取凭据内容、不启动客户端、不发网络
请求，也不写文件。来源还可按逗号分隔指定：`codex,claude,isambard,radar`。
开关作用于当前服务，同一服务的其他页面在下次刷新时同步。重启后恢复启动参数指定的状态。
Local Days 和 Refresh Seconds 不在网页显示，仅通过本地 `--days 60 --refresh 30` 等参数配置。

## 可选：Claude 限额捕获

本地 token 历史无需安装。若需要 5 小时／7 天订阅限额：

```sh
python3 claude_usage_statusline.py --install
```

随后让兼容的 Claude Code 客户端完成一次回复，桥接脚本就会保存经过筛选的快照。
网页刷新只读取快照。已有自定义 statusLine 不会被覆盖，除非显式传入 `--force`。
详细设置、卸载和 macOS 可选后台刷新（`expect`／`launchd`）见
[Claude 设置](docs/claude-setup.zh-CN.md)。

## 常用调整与排障

| 情况 | 处理方式 |
| --- | --- |
| 端口被占用 | 添加 `--port 8766` |
| 调整刷新间隔 | 添加 `--refresh 30` |
| Codex 在线限额缺失 | 检查 Codex 数据路径并登录 Codex |
| Claude 限额没有更新 | 检查快照时间和[限额捕获设置](docs/claude-setup.zh-CN.md) |
| 数据放在其他目录 | 设置 `CODEX_HOME`／`CLAUDE_CONFIG_DIR` |
| 不清楚当前配置 | 运行 `python3 codex_claude_usage_web.py --check` |

更新时运行 `git pull --ff-only`，重启服务并打开新打印的链接。移动仓库后，需要重新安装
引用旧绝对路径的 Claude statusLine／后台刷新器。

## 数据与隐私

服务默认监听 `127.0.0.1`。启动链接会建立认证会话，请勿分享。报告提取用量元数据，
不展示对话正文。Codex 在线接口并非公开稳定接口，可能随客户端服务变化。
本项目不是 OpenAI 或 Anthropic 官方工具。

公共缓存放在用户缓存目录，导出默认放在 `~/Downloads/codex-usage`，均可配置。
各来源独立处理失败，网页会先显示已完成的区块。详见
[配置与本地 API](WEB_DASHBOARD.md)及[隐私说明](docs/privacy.md)。

## 文档与开发

- [页面截图](docs/screenshots.md) · [Radar 规则](docs/radar.zh-CN.md)
- [配置、缓存位置和本地 API](WEB_DASHBOARD.md)
- [开发、测试与代码结构](docs/development.md)
- [原 Codex CLI 文档](README_OLD.md)

```sh
python3 -B -m unittest discover -v
```

只有 JavaScript 回归测试需要 Node.js。测试使用模拟数据和本地临时 HTTP 服务，
需要允许回环地址绑定端口，并检查是否出现跳过的测试。

## 来源与许可证

`codex_usage.py` 中的 Codex 采集与报告基础派生自
[MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)。
本仓库独立维护；组合网页、Claude 支持、Isambard 和 Radar 集成为 Frederick Zou 的新增实现。
[MIT 许可证](LICENCE)保留双方版权声明。
