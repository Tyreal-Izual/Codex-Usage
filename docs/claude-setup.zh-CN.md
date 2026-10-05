# Claude Code 设置

[返回快速开始](../README.zh-CN.md)

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

> 网页自动刷新只能重新读取已有快照。Claude Desktop 可能会持续写入本地 JSONL，
> 却不调用自定义 statusLine。此时 token 图表会继续更新，但 5 小时/7 天限额快照会
> 逐渐过期。页面会显示 snapshot age 和 stale 状态，避免把旧数据误认为账户实时用量。

页面还会执行本地 `claude auth status`，并且只返回经过脱敏的状态字段。认证检查明确成功
时，标题会显示绿色的 **CLI 登录 · 已登录**；认证检查明确返回未登录，并且限额快照已经
过期或不可用时，页面才显示红色的重新验证提示，并给出 `claude auth login` 恢复命令。
如果找不到 Claude 可执行文件、检查超时或认证输出无法识别，页面保持中性，不会显示
错误的绿色或红色结论。

### macOS 可选后台快照刷新

`claude_usage_refresher.py` 会在本仓库打开一个临时空白 Claude Code 会话，执行本地
`/usage` 命令，只解析 5 小时与 weekly 的百分比/reset 时间，写入同样经过筛选的快照
格式，然后使用 `Ctrl-D` 退出。`/usage` 会读取 plan limits，但不会向模型发送
prompt。刷新器不会恢复已有对话，也不会保存终端输出，并且可以独立于 statusLine
桥接工作。使用前需要确保 Claude Code 已登录，并且本仓库至少被信任过一次。
刷新器只为这个临时进程禁用 Remote Control，并启用 Claude 的屏幕阅读器输出，不会
修改用户的全局设置。它最多等待 30 秒，直到出现明确的交互输入提示，再等待 1 秒让
界面稳定，然后才发送 `/usage`。如果本地活动扫描导致页面多次更新，解析器只会分别
保留每个订阅窗口最后一组带明确标签的完整数值，不会按位置猜测无标签增量属于哪个窗口。

先测试一次刷新：

```sh
python3 claude_usage_refresher.py --once --force
```

安装支持 reset 感知的用户级 LaunchAgent：

```sh
python3 claude_usage_refresher.py --install
python3 claude_usage_refresher.py --status
```

需要移除时运行：

```sh
python3 claude_usage_refresher.py --uninstall
```

LaunchAgent 每 60 秒只读取一次本地快照，并不会每分钟都启动 Claude Code；普通完整
刷新仍约每 10 分钟一次。任一已保存的 reset 时间到达后，任务会等待 30 秒让账户状态
稳定，然后优先执行一次刷新，因此页面停留在 `Resets in now` 时通常会在 30–90 秒内
恢复。`usage-dashboard-refresh-state.json` 只记录尝试时间、reset 时间戳、退出状态和
连续失败次数。任何完整刷新失败或意外中断后，都会依次退避 5、10、20、最多 40 分钟，
避免 `/usage` 解析失效时每分钟重复启动 Claude。两个订阅窗口会独立解析：其中一个缺失
或无效时仍保留另一个有效窗口；超出 0–100 的百分比会被拒绝，而不是钳成错误的 100%。
原有进程锁继续防止任务重叠，并清理卡住的 Claude 进程。日志仍位于
`~/.claude/usage-refresh*.log`。

任务只会在 Mac 已唤醒且用户已登录时运行。从旧版 10 分钟调度升级、移动仓库或移动
Claude 可执行文件后，需要重新执行 `--install`。这是 Claude Code 客户端自动化，并非
Anthropic 提供的后台用量 API，因此未来的 Claude Code 版本可能需要相应调整。
