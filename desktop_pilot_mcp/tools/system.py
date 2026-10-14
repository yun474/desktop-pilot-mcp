"""系统工具：PowerShell、文件、注册表、进程。

这些操作不涉及屏幕，放到默认线程池执行，不占用桌面操作线程，长命令运行期间仍可截图和点击。
"""

import asyncio
from typing import Annotated, Literal

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from ..config import ToolsConfig
from ..core import files, processes, registry, shell
from .common import Content, Registrar, guarded, optional, text


def register(reg: Registrar, tools_cfg: ToolsConfig) -> None:
    on = tools_cfg.enabled
    limit = tools_cfg.output_limit

    async def run(func, *args) -> Content:
        return text(shell.truncate(await guarded(asyncio.to_thread(func, *args)), limit))

    if on["shell"]:
        @reg.tool("shell", "在这台电脑上执行 PowerShell 命令并返回输出，可用于查询系统信息、批量处理文件、运行脚本等。"
                           f"默认超时 {tools_cfg.shell_timeout} 秒。启动图形界面程序请用 Start-Process，"
                           "否则命令会一直等到程序关闭才返回。", destructive=True)
        async def run_shell(
            command: Annotated[str, Field(description="PowerShell 命令或脚本")],
            timeout: Annotated[int | None, optional(
                "integer", f"超时秒数，默认 {tools_cfg.shell_timeout}，最多 {tools_cfg.shell_max_timeout}")] = None,
            cwd: Annotated[str | None, optional("string", "工作目录，默认为用户主目录")] = None,
        ) -> Content:
            seconds = min(timeout or tools_cfg.shell_timeout, tools_cfg.shell_max_timeout)
            result = await guarded(asyncio.to_thread(shell.run_powershell, command, max(1, seconds), cwd))
            parts = [f"退出码：{result.exit_code}" + (f"（{seconds} 秒超时，已强制结束）" if result.timed_out else "")]
            if result.stdout:
                parts.append(f"输出：\n{result.stdout}")
            if result.stderr:
                parts.append(f"错误输出：\n{result.stderr}")
            if not result.stdout and not result.stderr:
                parts.append("（没有输出）")
            return text(shell.truncate("\n".join(parts), limit))

    if on["file"]:
        @reg.tool("file", "管理这台电脑上的文件：read=读取文本文件，write=写入（append=true 追加），copy=复制，move=移动或重命名，"
                          "delete=删除（移入回收站，可还原），list=列出文件夹内容，search=按文件名通配符递归搜索，info=查看详细信息。"
                          "相对路径以用户主目录为基准，支持 ~ 和 %USERPROFILE% 等写法。", destructive=True)
        async def file(
            action: Annotated[Literal["read", "write", "copy", "move", "delete", "list", "search", "info"],
                              Field(description="操作类型")],
            path: Annotated[str, Field(description="文件或文件夹路径；copy/move 时为源路径")],
            destination: Annotated[str | None, optional("string", "copy/move 的目标路径（可以是已存在的文件夹）")] = None,
            content: Annotated[str | None, optional("string", "write 时写入的内容")] = None,
            append: Annotated[bool, Field(description="write 时是否追加到文件末尾")] = False,
            pattern: Annotated[str | None, optional("string", "list 时的文件名过滤，或 search 时的文件名通配符，例如 *.docx、*报告*")] = None,
            offset: Annotated[int, Field(description="read 时从第几行开始（从 1 开始）")] = 1,
            lines: Annotated[int, Field(description="read 时最多读取的行数（最多 500）")] = 200,
        ) -> Content:
            if action == "read":
                return await run(files.read, path, offset, lines)
            if action == "write":
                if content is None:
                    raise_missing("content")
                return await run(files.write, path, content, append)
            if action in ("copy", "move"):
                if not destination:
                    raise_missing("destination")
                return await run(files.copy if action == "copy" else files.move, path, destination)
            if action == "delete":
                return await run(files.delete, path)
            if action == "list":
                return await run(files.list_dir, path, pattern or "*")
            if action == "search":
                return await run(files.search, path, pattern or "")
            return await run(files.info, path)

    if on["registry"]:
        @reg.tool("registry", "读写 Windows 注册表：get=读取值，set=创建或修改值，delete=删除值（提供 name）或整个键（不提供 name，"
                              "连同所有子键），list=列出子键和值。路径写法如 HKCU\\Software\\MyApp 或 HKLM:\\SOFTWARE\\Microsoft。"
                              "修改 HKLM 需要以管理员身份运行本服务。", destructive=True)
        async def reg_tool(
            action: Annotated[Literal["get", "set", "delete", "list"], Field(description="操作类型")],
            path: Annotated[str, Field(description="注册表键路径")],
            name: Annotated[str | None, optional("string", "值名称，空字符串表示默认值")] = None,
            value: Annotated[str | None, optional("string", "set 时的数据；DWORD/QWORD 写数字，MULTI_SZ 用换行分隔，BINARY 写十六进制")] = None,
            value_type: Annotated[Literal["REG_SZ", "REG_EXPAND_SZ", "REG_DWORD", "REG_QWORD", "REG_MULTI_SZ", "REG_BINARY"],
                                  Field(description="set 时的值类型")] = "REG_SZ",
        ) -> Content:
            if action == "get":
                return await run(registry.get, path, name or "")
            if action == "set":
                if value is None:
                    raise_missing("value")
                return await run(registry.set_value, path, name or "", value, value_type)
            if action == "delete":
                return await run(registry.delete, path, name)
            return await run(registry.list_key, path)

    if on["process"]:
        @reg.tool("process", "查看或结束进程：list=列出进程（可按名称过滤，按内存、CPU 或名称排序），"
                             "kill=按 PID 或进程名结束进程（同名进程会全部结束）。系统关键进程不允许结束。", destructive=True)
        async def process(
            action: Annotated[Literal["list", "kill"], Field(description="操作类型")],
            name: Annotated[str, Field(description="list 时按名称过滤；kill 时要结束的进程名，例如 notepad 或 notepad.exe")] = "",
            pid: Annotated[int | None, optional("integer", "kill 时要结束的进程 PID，优先于 name")] = None,
            sort_by: Annotated[Literal["memory", "cpu", "name"], Field(description="list 时的排序方式")] = "memory",
            limit: Annotated[int, Field(description="list 时最多显示的进程数")] = 30,
            force: Annotated[bool, Field(description="kill 时是否强制结束（不给程序保存的机会）")] = False,
        ) -> Content:
            if action == "list":
                return await run(processes.list_processes, name, sort_by, limit)
            return await run(processes.kill, pid, name, force)


def raise_missing(param: str):
    raise ToolError(f"缺少参数 {param}")
