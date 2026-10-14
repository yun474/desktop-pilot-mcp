"""执行 PowerShell 命令。

参考 Windows-MCP（MIT）desktop/powershell.py：用 -EncodedCommand 传递脚本避免转义问题，
并同时设置 $OutputEncoding 与 [Console]::OutputEncoding，保证中文和原生程序的输出不乱码。
"""

from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass

_CREATE_NO_WINDOW = 0x08000000
_PRELUDE = (
    "$OutputEncoding = [System.Text.Encoding]::UTF8; "
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$ProgressPreference = 'SilentlyContinue'; "
)


@dataclass
class ShellResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def _kill_tree(pid: int) -> None:
    # 只结束 powershell 本身的话，它启动的子进程会继续占着输出管道，导致读取一直卡住
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                   creationflags=_CREATE_NO_WINDOW)


def run_powershell(command: str, timeout: float, cwd: str | None = None) -> ShellResult:
    encoded = base64.b64encode((_PRELUDE + command).encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, NO_COLOR="1")
    proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-OutputFormat", "Text", "-EncodedCommand", encoded],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or os.path.expanduser("~"),
        env=env,
        creationflags=_CREATE_NO_WINDOW,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    return ShellResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=out.decode("utf-8", errors="replace").rstrip(),
        stderr=err.decode("utf-8", errors="replace").rstrip(),
        timed_out=timed_out,
    )


def ps_quote(text: str) -> str:
    """转成 PowerShell 单引号字符串字面量。"""
    return "'" + text.replace("'", "''") + "'"


def truncate(text: str, limit: int) -> str:
    """超长输出保留开头和结尾，中间省略。"""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n\n……（中间省略 {len(text) - limit} 个字符）……\n\n{text[-tail:]}"
