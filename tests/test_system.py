"""系统工具测试：PowerShell、文件、注册表、进程、网页抓取。在真实 Windows 环境中运行。"""

import asyncio
import os
import threading
import winreg
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from desktop_pilot_mcp.core import files, processes, registry, scrape, shell

TEST_KEY = r"HKCU\Software\DesktopPilotMcpTest"


# ---------------- PowerShell ----------------

def test_shell_unicode_and_exit_code():
    r = shell.run_powershell("Write-Output '中文输出'; cmd /c echo 原生程序; exit 3", timeout=30)
    assert "中文输出" in r.stdout and "原生程序" in r.stdout
    assert r.exit_code == 3 and not r.timed_out


def test_shell_timeout_kills_tree():
    r = shell.run_powershell("Start-Sleep -Seconds 30", timeout=2)
    assert r.timed_out


def test_shell_cwd(tmp_path):
    r = shell.run_powershell("(Get-Location).Path", timeout=30, cwd=str(tmp_path))
    assert r.stdout.strip().lower() == str(tmp_path).lower()


def test_truncate_keeps_head_and_tail():
    out = shell.truncate("A" * 100 + "B" * 100, 50)
    assert out.startswith("A") and out.endswith("B") and "省略" in out


# ---------------- 文件 ----------------

def test_file_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    assert "新建" in files.write(str(f), "第一行\n第二行\n")
    files.write(str(f), "第三行\n", append=True)
    text = files.read(str(f), offset=2, limit=1)
    assert "共 3 行" in text and text.endswith("第二行") and "offset=3" in text

    files.copy(str(f), str(tmp_path / "sub"))  # 目标文件夹不存在时当作目标文件名
    assert (tmp_path / "sub").read_text(encoding="utf-8").startswith("第一行")
    os.makedirs(tmp_path / "dir")
    files.move(str(tmp_path / "sub"), str(tmp_path / "dir"))  # 已存在的文件夹：移动到其中
    assert (tmp_path / "dir" / "sub").exists()
    with pytest.raises(FileExistsError):
        files.copy(str(f), str(tmp_path / "dir" / "sub"))

    assert "a.txt" in files.list_dir(str(tmp_path), "*.txt")
    assert "sub" in files.search(str(tmp_path), "su*")
    assert "大小" in files.info(str(f))


def test_file_read_gbk_and_binary(tmp_path):
    (tmp_path / "gbk.txt").write_bytes("老文件编码".encode("gbk"))
    assert "老文件编码" in files.read(str(tmp_path / "gbk.txt"))
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError):
        files.read(str(tmp_path / "bin.dat"))


def test_file_delete_to_recycle_bin(tmp_path):
    f = tmp_path / "dp_test.txt"
    f.write_text("x", encoding="utf-8")
    assert "回收站" in files.delete(str(f))
    assert not f.exists()


def test_relative_path_uses_home():
    assert files.resolve("Desktop") == files.Path.home() / "Desktop"


# ---------------- 注册表 ----------------

@pytest.fixture
def test_key():
    yield TEST_KEY
    try:
        registry.delete(TEST_KEY, None)
    except OSError:
        pass


def test_registry_roundtrip(test_key):
    registry.set_value(test_key, "Name", "值")
    registry.set_value(test_key, "Count", "0x10", "REG_DWORD")
    registry.set_value(test_key, "Lines", "a\nb", "REG_MULTI_SZ")
    registry.set_value(test_key + r"\Child", "", "默认值")
    assert "= 值" in registry.get(test_key, "Name")
    assert "= 16" in registry.get(test_key.replace("HKCU", "HKCU:"), "Count")
    assert "a | b" in registry.get(test_key, "Lines")
    listing = registry.list_key(test_key)
    assert "Child" in listing and "Count" in listing

    registry.delete(test_key, "Name")
    with pytest.raises(FileNotFoundError):
        registry.get(test_key, "Name")
    registry.delete(test_key, None)  # 连同子键一起删除
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\DesktopPilotMcpTest")


def test_registry_bad_root():
    with pytest.raises(ValueError):
        registry.get(r"HKXX\Software", "a")


# ---------------- 进程 ----------------

def test_process_list_and_protection():
    out = processes.list_processes("python", "memory", 5)
    assert "python" in out.lower()
    assert "拒绝结束" in processes.kill(pid=os.getpid())
    assert "拒绝结束" in processes.kill(name="csrss")
    with pytest.raises(LookupError):
        processes.kill(pid=999999)
    with pytest.raises(LookupError):
        processes.kill(name="definitely_not_running_xyz")


# ---------------- 网页抓取 ----------------

_PAGE = """<html><head><meta charset="gbk"><title>测试页面</title><script>var x=1;</script></head>
<body><nav>导航</nav><main><h1>标题</h1><p>正文内容<a href="/x">链接</a></p></main></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = _PAGE.encode("gbk")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_scrape_html_gbk():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        out = asyncio.run(scrape.scrape(url, 0, 20000))
        assert "标题：测试页面" in out and "# 标题" in out and "正文内容" in out
        assert "var x" not in out and "导航" not in out  # 脚本被移除，只取 main
        part = asyncio.run(scrape.scrape(url, 0, 3))
        assert "offset=3" in part
    finally:
        server.shutdown()
