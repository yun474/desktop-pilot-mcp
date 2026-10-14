# Desktop Pilot MCP

通过截图操控 Windows 电脑的 MCP 服务器：看屏幕、点按钮、打字、滚动、拖拽、切换和启动程序。

装在**被操控的电脑**上，AstrBot 等 MCP 客户端通过 Tailscale 等内网远程连接。专门解决高分屏笔记本上「模型算的坐标总是点歪」的问题，支持同时控制多台电脑。

## 为什么会点歪

以 2560×1600、缩放 150% 的笔记本为例：截图发给模型前会被缩小（比如缩到 1728×1080），模型报出的是缩小图上的坐标，但点击工具把它当成真实屏幕坐标，于是整体往左上角偏。很多模型服务商还会把图片再压缩一次，模型自己都不知道图被缩了多少。

## 本项目的做法

1. **元素编号优先**：通过 Windows UI Automation 读取按钮、输入框等可交互元素的真实位置，在截图上画框编号。模型只需说「点 12 号」，服务端直接点击元素中心，完全不受分辨率和缩放影响。
2. **坐标自动换算**：每张返回给模型的图片都记录了它覆盖的屏幕区域和尺寸，模型给出的坐标由服务端换算成物理像素，模型不需要做任何计算。
3. **千分比坐标**：默认使用 0~1000 的千分比坐标，这是 Qwen-VL、豆包、Gemini 等模型训练时使用的格式；即使服务商再次压缩图片，比例也不会变。使用 GPT、Claude 时可切换为图片像素坐标。
4. **放大镜**：游戏、画布等读不到元素的场景，模型可以先放大某个区域再精确定位，两次缩放由服务端一并换算。
5. **DPI 正确**：在专用线程上启用 Per-Monitor V2 DPI 感知，截图、元素位置、鼠标坐标统一使用物理像素，多显示器、缩放比例不同的显示器都能对齐。

## 提供的工具

工具名带有电脑名前缀（配置里的 `server.name`），下表以 `laptop` 为例。

**桌面操作**（始终开启）

| 工具 | 作用 |
| --- | --- |
| `laptop_screenshot` | 截图并标注元素编号，返回元素列表 |
| `laptop_zoom` | 放大查看最近一张图片中的某块区域 |
| `laptop_click` | 按编号或坐标点击（左/右/中键，单击/双击/仅移动） |
| `laptop_type` | 输入文字（支持中文，不经过输入法），可先点击目标、清空、回车 |
| `laptop_scroll` | 滚动滚轮 |
| `laptop_drag` | 拖拽 |
| `laptop_hotkey` | 按键或组合键 |
| `laptop_app` | 列出、切换窗口，从开始菜单启动应用，最大化/最小化/还原，调整窗口位置和大小 |
| `laptop_wait` | 等待几秒，等程序加载 |

**可选工具**（默认全部开启，可在 `config.toml` 的 `[tools]` 中逐个关闭）

| 工具 | 开关 | 作用 |
| --- | --- | --- |
| `laptop_multi_click` | `multi` | 依次点击多处，可按住 Ctrl 多选 |
| `laptop_multi_type` | `multi` | 一次填写多个输入框 |
| `laptop_clipboard` | `clipboard` | 读写剪贴板 |
| `laptop_notify` | `notify` | 在右下角弹出系统通知 |
| `laptop_shell` | `shell` | 执行 PowerShell 命令（带超时，输出过长自动截断） |
| `laptop_file` | `file` | 读、写、复制、移动、删除（移入回收站）、列目录、搜索文件 |
| `laptop_registry` | `registry` | 读写、删除、列出注册表项 |
| `laptop_process` | `process` | 查看进程（按内存/CPU/名称排序）、结束进程（系统关键进程不允许结束） |
| `laptop_scrape` | `scrape` | 抓取网页正文并转成 Markdown，只读网页时比截图更省 token |

## 安装（在被操控的电脑上）

1. 安装 [uv](https://docs.astral.sh/uv/)（Python 环境与依赖由 uv 自动处理）。
2. 下载本项目：`git clone https://github.com/yun474/desktop-pilot-mcp.git`
3. 双击 `start.bat`。首次运行会自动安装依赖，并生成 `config.toml`（自动创建随机访问令牌）。
4. 控制台会打印 AstrBot 用的连接配置，把其中的 `<这台电脑的 Tailscale IP>` 换成这台电脑在 Tailscale 里的 IP（`100.x.x.x`）。
5. 按需修改 `config.toml`（电脑名、端口、坐标模式等），改完重启生效。

### 防火墙

首次启动时 Windows 可能弹出防火墙提示，请允许访问。如果没有弹出或之前点了拒绝，可以用**管理员**命令行添加一条只允许 Tailscale 网段访问的规则（端口按配置修改）：

```bat
netsh advfirewall firewall add rule name="Desktop Pilot MCP" dir=in action=allow protocol=TCP localport=8765 remoteip=100.64.0.0/10
```

### 开机自启

确认 `start.bat` 能正常运行后，关闭它，双击 `install_autostart.bat`。之后每次登录 Windows 都会在后台静默运行（没有窗口），日志写在项目目录下的 `desktop-pilot.log`。

- `stop.bat`：停止后台运行的实例
- `uninstall_autostart.bat`：取消开机自启

> 必须在已登录的桌面会话中运行，不能做成 Windows 服务：服务看不到桌面，无法截图和操作。电脑锁屏或睡眠时也无法操作。

## 接入 AstrBot

1. AstrBot WebUI 侧边栏进入「MCP」，添加服务器，名称填电脑名（如 `laptop`），配置填 `start.bat` 打印的内容：

   ```json
   {
     "transport": "streamable_http",
     "url": "http://100.x.x.x:8765/mcp",
     "headers": { "Authorization": "Bearer 你的令牌" }
   }
   ```

2. **设置工具权限（重要）**：AstrBot 中 MCP 工具默认所有用户都能调用。请在「MCP」页面的函数工具列表里，把这台电脑的所有工具的「权限」改为「管理员」，否则群里任何人都能让 bot 操控你的电脑。需要 AstrBot 4.28.1 及以上版本。
3. 使用支持图片输入的模型，并确认该模型提供商的「模态」配置包含图片。
4. 对 bot 说「帮我在笔记本上打开记事本写一段话」之类的指令即可。

### 配套 Skill

`skills/desktop-pilot/SKILL.md` 是配套的使用说明，教模型先截图再按编号操作、坐标与放大镜的用法、什么情况下改用 shell / file / scrape 等工具、多台电脑如何区分，以及删除文件、结束进程等操作前要先征得用户同意。装上后模型用这些工具会稳很多。

1. 把 `skills/desktop-pilot` 文件夹压缩成 zip（右键 → 压缩为 ZIP 文件）。
2. AstrBot WebUI 进入「插件」→「技能」→「上传技能」，选择这个 zip。
3. AstrBot 配置中的「电脑使用」（`computer_use_runtime`）需要设为 `local` 或 `sandbox`：模型要执行命令读取 SKILL.md 的完整内容，设为 `none` 时 Skill 不会生效。

Skill 里用 `<pc>_` 代指工具名前缀，多台电脑共用同一份即可，不需要按电脑名修改。

### 控制多台电脑

每台电脑各装一份，`config.toml` 里的 `server.name` 设成不同的名字（如 `laptop`、`pc`），在 AstrBot 中分别添加。工具名和描述都带有电脑名，模型能区分要操作哪一台。

> AstrBot 不会给 MCP 工具加服务器名前缀，同名工具会互相覆盖，所以多台电脑的 `server.name` 一定不能相同。

其他支持 Streamable HTTP 的 MCP 客户端也可以用同样的地址和请求头连接。

## 配置说明（config.toml）

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `server.name` | laptop | 电脑名，作为工具名前缀；只能用字母、数字、下划线，留空则前缀为 `desktop_` |
| `server.host` | 0.0.0.0 | 监听地址，也可填本机 Tailscale IP 只接受 Tailscale 连接 |
| `server.port` | 8765 | 端口 |
| `server.token` | 自动生成 | 访问令牌，监听非本机地址时必须设置 |
| `desktop.coord_mode` | normalized | `normalized` 千分比，`pixel` 图片像素 |
| `desktop.max_long_edge` | 1280 | 截图最长边，越大越清晰，越费 token |
| `desktop.image_format` / `jpeg_quality` | jpeg / 80 | png 无损但体积大 |
| `desktop.annotate` | true | 关闭后只能用坐标操作 |
| `desktop.max_elements` | 120 | 最多标注元素数，前台窗口优先 |
| `desktop.element_timeout` | 3.0 | 读取元素超时（秒） |
| `desktop.default_display` | 0 | 0 前台窗口所在显示器，-1 全部，1、2… 指定 |
| `desktop.type_method` | unicode | 个别程序不认时改为 paste（剪贴板粘贴，完成后恢复剪贴板） |
| `desktop.screenshot_after_action` | false | 开启后动作完成自动附带新截图 |
| `desktop.action_delay` | 0.6 | 自动截图前等待（秒） |
| `desktop.blocked_hotkeys` | win+l、ctrl+alt+delete | 禁止模型按下的组合键，可加入 alt+f4、win+r 等 |
| `tools.multi` … `tools.scrape` | 全部 true | 各个可选工具的开关，见上方「可选工具」表 |
| `tools.shell_timeout` | 30 | PowerShell 默认超时（秒） |
| `tools.shell_max_timeout` | 300 | 模型单次调用允许指定的最长超时（秒） |
| `tools.output_limit` | 20000 | 命令输出、文件内容、网页正文单次返回的最大字符数 |

## 安全提醒

能操控电脑的 bot 权限极大，等同于把鼠标键盘交给了对它说话的人。尤其是 `shell`、`file`、`registry`、`process` 这几个工具默认开启，能执行任意命令、删除文件、修改系统设置：

- 用不到的工具请在 `config.toml` 的 `[tools]` 中关掉
- 令牌相当于这台电脑的遥控器钥匙，不要泄露；泄露后把 `config.toml` 中的 token 换成新的随机字符串（或删除整个 `config.toml` 让程序重新生成），再同步更新 AstrBot 里的配置
- 只在 Tailscale 等内网中使用，不要把端口暴露到公网
- 在 AstrBot 中把工具权限设为「管理员」（所有工具都要设，包括上面这几个）
- `file` 删除的文件会进回收站，误删可以还原；`process` 不允许结束系统关键进程

## 已知限制

- 以管理员权限运行的程序（任务管理器、部分安装程序）会拦截普通权限进程的模拟输入，需要本服务也以管理员身份运行才能操作。
- 锁屏、UAC 安全桌面、睡眠时无法截图和操作。
- 游戏、视频播放器等自绘界面读不到元素，只能用坐标和放大镜。
- 未开启无障碍支持的 Electron 应用（如部分版本的 QQ）读不到元素；Firefox 网页内的元素读不到。

## 开发

```bash
uv sync
uv run pytest
```

## 致谢

设计思路和系统工具的功能范围参考了 [Windows-MCP](https://github.com/CursorTouch/Windows-MCP)（MIT License），详见 `NOTICE`。

## 许可证

MIT
