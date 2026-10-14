# 更新日志

## v2.0.0

由 AstrBot 插件改为独立的 MCP 服务器，项目更名为 desktop-pilot-mcp。

- 装在被操控的电脑上，AstrBot 等 MCP 客户端通过 Tailscale 等内网远程连接（Streamable HTTP）
- 访问令牌校验（`Authorization: Bearer`），首次启动自动生成；监听非本机地址时未设置令牌会拒绝启动
- 工具名带电脑名前缀（如 `laptop_screenshot`），支持同时控制多台电脑
- 配置改为 `config.toml`
- 提供 `start.bat`、开机自启（`install_autostart.bat` / `uninstall_autostart.bat`）与 `stop.bat`
- 后台运行时日志写入 `desktop-pilot.log`，令牌不写入日志
- 可选参数的 schema 只声明基础类型，兼容更多模型
- 移除 AstrBot 插件形态；权限控制改用 AstrBot 自带的工具权限设置

新增工具（功能范围参考 Windows-MCP）：

- `wait`：等待程序加载
- `multi_click` / `multi_type`：批量点击（可按住 Ctrl 多选）、一次填写多个输入框
- `clipboard`：读写剪贴板
- `notify`：右下角系统通知
- `shell`：执行 PowerShell 命令，带超时（超时结束整个进程树）与输出截断，中文不乱码
- `file`：读写、复制、移动、删除（移入回收站）、列目录、搜索、查看信息，兼容 GBK 编码的旧文件
- `registry`：注册表读写、删除（可连同子键）、列出
- `process`：查看与结束进程，系统关键进程不允许结束
- `scrape`：抓取网页正文转为 Markdown，支持分段读取长网页
- `app` 新增 `maximize`、`minimize`、`restore`、`resize`，调整位置时自动补偿 Win10/11 的透明边框
- 可选工具都可以在 `config.toml` 的 `[tools]` 中单独关闭；系统工具在独立线程执行，长命令运行期间不影响截图和点击

配套 Skill：

- 新增 `skills/desktop-pilot/SKILL.md`，可上传到 AstrBot 的技能中，教模型正确使用这些工具：先截图后操作、优先按编号、坐标与放大镜规则、按需求选择工具、多台电脑区分，以及危险操作前先征得用户同意

## v1.0.0

- 首个版本（AstrBot 插件）
- 截图标注可交互元素编号，模型可按编号操作
- 模型坐标自动换算为物理像素，支持千分比与图片像素两种坐标模式
- 放大镜工具，放大图中的坐标同样自动换算
- 点击、输入、滚动、拖拽、组合键、窗口切换与应用启动
- 管理员权限控制与组合键黑名单
