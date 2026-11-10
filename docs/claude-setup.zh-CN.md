# macOS Claude Code 额度采集

[快速开始](../README.zh-CN.md) · [English](claude-setup.md)

本地 token 历史直接读取 `~/.claude/projects/**/*.jsonl`，无需配置。
token 汇总规则见[统计口径](development.md#data-boundaries)。
5 小时和 7 天额度读取 `~/.claude/usage-dashboard.json` 快照；应用刷新不会强制更新账户额度。
7 天额度只表示所有模型的总额度；Fable 等模型专属额度不会覆盖或替代它，即使总额度缺失也一样。

## 状态栏采集

构建应用后，在仓库目录运行：

```sh
HELPER="$PWD/dist/Usage.app/Contents/Resources/helper/usage-helper"
"$HELPER" --statusline --install
"$HELPER" --statusline --status
```

如果已移入 Applications，将 `HELPER` 改为
`/Applications/Usage.app/Contents/Resources/helper/usage-helper`。

随后在兼容的 Claude Code 客户端完成一次回复。已有自定义状态栏会保留，只有显式
使用 `--force` 才覆盖。卸载用 `"$HELPER" --statusline --uninstall`；移动应用后重新安装。
源码环境改用 `python3 claude_usage_statusline.py` 和相同参数。
没有可用快照时，应用会显示对应的安装命令。

## 可选后台刷新

通过已登录 Claude CLI 的 `/usage` 界面采集，不发送提示词、不恢复会话。
需要 `expect` 与一个已被 Claude 信任的项目，请显式指定项目；不会自动确认信任提示。

```sh
"$HELPER" --refresh-claude --once --force --project-dir "$PWD"
"$HELPER" --refresh-claude --install --project-dir "$PWD"
"$HELPER" --refresh-claude --status
# 移除定时任务：
"$HELPER" --refresh-claude --uninstall
```

源码环境将 `"$HELPER" --refresh-claude` 换成 `python3 claude_usage_refresher.py`。
任务每分钟检查，通常约十分钟完整刷新一次，额度重置后优先检查；失败退避 5–40 分钟。
仅在 Mac 唤醒且用户登录时运行。移动应用、项目或 Claude 可执行文件后需重新安装任务。

快照只保存额度、重置时间和采集元数据。过期数据会标注；快照过期或不可用且 CLI
明确退出登录时，提示 `claude auth login`。CLI 缺失或检查超时不视为已退出登录。
采集工具与应用应使用一致的[路径配置](development.md#configuration)。
