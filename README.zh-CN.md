[English](README.md) | **简体中文**

# Usage for Mac

原生 SwiftUI 仪表盘，集中查看 Codex 和 Claude Code 额度、token、模型与会话，
并集成 Isambard 状态和 Codex Radar。**仅支持 macOS 14.4+。**

## 构建与启动

构建需要完整 Xcode 15.3+ 和 Python 3.10+；单独安装 Command Line Tools 不足以构建。
先用 `⌘Q` 完全退出 Usage，再在仓库目录运行：

```sh
./scripts/build_macos.sh
open dist/Usage.app
```

首次构建在 `.build/python` 中安装 PyInstaller。生成的 App 自带 Python，运行时
无需终端、浏览器或另装 Python/Node。按构建机器的 CPU 架构生成；本地使用临时签名，
公开分发前仍需 Developer ID 签名与公证。

## 使用

总览顺序：**额度 → Isambard → 模型统计 → Codex Reset Credits → Radar**。
Codex 与 Claude 额度上下各占一整行，模型卡片在空间足够时并排展示。
紧凑卡片保留重置倒计时、可展开的服务详情和重置额度到期提示；标题按需换行，数值变化时短暂高亮。

- **设置（`⌘,`）**：来源、中英文、刷新间隔和每日历史行数。
- **回到额度**：将 Codex 额度对齐到顶部；启动加载后自动定位一次，后续刷新保持滚动位置。
- **刷新（`⌘R`）**：按来源缓存策略更新；Radar 每四小时同步。
  采集中或断连后，工具栏和菜单栏均提供**重新连接**。
- **导出**：将当前报表、更新时间和错误信息保存为 JSON。
- **菜单栏**：显示剩余额度及对应窗口；短期窗口不可用时显示周额度。关窗后继续运行，`⌘Q` 完全退出。

Codex 与 Claude 可独立使用。本地历史无需安装采集插件；Codex 在线额度需要已登录，Claude 订阅额度需按
[采集说明](docs/claude-setup.zh-CN.md)配置。遇到问题可在设置中检查配置或重新连接采集器。

## 参考

- [开发、配置与检查](docs/development.md) · [统计口径](docs/development.md#data-boundaries)
- [Radar 规则](docs/radar.zh-CN.md) · [隐私](docs/privacy.md)
- [旧 CLI](README_OLD.md) · [旧网页 API](WEB_DASHBOARD.md)

Codex 采集核心源自 [MacSteini/Codex-Usage](https://github.com/MacSteini/Codex-Usage)，
原生应用与新增集成由 Frederick Zou 独立维护。[MIT 许可](LICENCE)保留双方版权声明。
本项目非 OpenAI 或 Anthropic 官方应用。
