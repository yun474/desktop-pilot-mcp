"""文件管理。相对路径以当前用户主目录为基准；删除时移入回收站，误删可以找回。"""

from __future__ import annotations

import ctypes
import fnmatch
import os
import shutil
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

READ_LINE_LIMIT = 500
LIST_LIMIT = 300
SEARCH_LIMIT = 200
_TEXT_ENCODINGS = ("utf-8-sig", "gb18030")


def resolve(path: str) -> Path:
    if not path.strip():
        raise ValueError("请提供路径")
    p = Path(os.path.expandvars(os.path.expanduser(path.strip().strip('"'))))
    if not p.is_absolute():
        p = Path.home() / p
    return p


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def read(path: str, offset: int = 1, limit: int = 200) -> str:
    p = resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在：{p}")
    raw = p.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError(f"{p.name} 看起来是二进制文件，无法按文本读取")
    for enc in _TEXT_ENCODINGS:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    offset = max(1, offset)
    limit = max(1, min(limit, READ_LINE_LIMIT))
    chunk = lines[offset - 1 : offset - 1 + limit]
    end = offset - 1 + len(chunk)
    header = f"{p}（共 {len(lines)} 行，显示第 {offset}~{end} 行）"
    if end < len(lines):
        header += f"，还有后续内容，可用 offset={end + 1} 继续读取"
    return header + "\n" + "\n".join(chunk)


def write(path: str, content: str, append: bool = False) -> str:
    p = resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    with p.open("a" if append else "w", encoding="utf-8", newline="") as f:
        f.write(content)
    action = "追加到" if append else ("覆盖写入" if existed else "新建")
    return f"已{action} {p}（{len(content)} 个字符）"


def copy(src: str, dst: str) -> str:
    s, d = resolve(src), resolve(dst)
    if not s.exists():
        raise FileNotFoundError(f"源路径不存在：{s}")
    if d.is_dir():
        d = d / s.name
    if d.exists():
        raise FileExistsError(f"目标已存在：{d}，请先删除或换一个名字")
    d.parent.mkdir(parents=True, exist_ok=True)
    if s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return f"已复制 {s} -> {d}"


def move(src: str, dst: str) -> str:
    s, d = resolve(src), resolve(dst)
    if not s.exists():
        raise FileNotFoundError(f"源路径不存在：{s}")
    if d.is_dir():
        d = d / s.name
    if d.exists():
        raise FileExistsError(f"目标已存在：{d}，请先删除或换一个名字")
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"已移动 {s} -> {d}"


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


_FO_DELETE = 3
_FOF_SILENT, _FOF_NOCONFIRMATION, _FOF_ALLOWUNDO, _FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400


def delete(path: str) -> str:
    """移入回收站。目录连同内容一起移入。"""
    p = resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"路径不存在：{p}")
    kind = "文件夹" if p.is_dir() else "文件"
    op = _SHFILEOPSTRUCTW(
        wFunc=_FO_DELETE,
        pFrom=str(p) + "\0",  # 结构体要求以两个 \0 结尾，ctypes 会再补一个
        fFlags=_FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI,
    )
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted:
        raise OSError(f"删除失败（错误码 {code}），文件可能正被占用或没有权限：{p}")
    return f"已将{kind} {p} 移入回收站，误删可以从回收站还原"


def list_dir(path: str, pattern: str = "*") -> str:
    p = resolve(path)
    if not p.is_dir():
        raise NotADirectoryError(f"不是文件夹：{p}")
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    entries = [e for e in entries if fnmatch.fnmatch(e.name.lower(), pattern.lower())]
    lines = [f"{p}（共 {len(entries)} 项）"]
    for e in entries[:LIST_LIMIT]:
        try:
            if e.is_dir():
                lines.append(f"[目录] {e.name}  {_mtime(e)}")
            else:
                lines.append(f"[文件] {e.name}  {_size(e.stat().st_size)}  {_mtime(e)}")
        except OSError:
            lines.append(f"[无法访问] {e.name}")
    if len(entries) > LIST_LIMIT:
        lines.append(f"……还有 {len(entries) - LIST_LIMIT} 项未列出，可用 pattern 过滤")
    return "\n".join(lines)


def search(path: str, pattern: str) -> str:
    """按文件名通配符递归搜索，例如 *.docx、*报告*。"""
    root = resolve(path)
    if not root.is_dir():
        raise NotADirectoryError(f"不是文件夹：{root}")
    if not pattern.strip():
        raise ValueError("请提供要搜索的文件名，例如 *.docx")
    pat = pattern.lower()
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过隐藏目录和体积巨大的依赖目录，避免搜索耗时过长
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        for name in dirnames + filenames:
            if fnmatch.fnmatch(name.lower(), pat):
                hits.append(os.path.join(dirpath, name))
                if len(hits) >= SEARCH_LIMIT:
                    return f"在 {root} 中找到至少 {SEARCH_LIMIT} 个结果（已截断）：\n" + "\n".join(hits)
    if not hits:
        return f"在 {root} 中没有找到匹配「{pattern}」的文件"
    return f"在 {root} 中找到 {len(hits)} 个结果：\n" + "\n".join(hits)


def info(path: str) -> str:
    p = resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"路径不存在：{p}")
    st = p.stat()
    fmt = "%Y-%m-%d %H:%M:%S"
    lines = [
        f"路径：{p}",
        f"类型：{'文件夹' if p.is_dir() else '文件'}",
        f"创建时间：{datetime.fromtimestamp(st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime).strftime(fmt)}",
        f"修改时间：{datetime.fromtimestamp(st.st_mtime).strftime(fmt)}",
    ]
    if p.is_file():
        lines.insert(2, f"大小：{_size(st.st_size)}（{st.st_size} 字节）")
    else:
        count = sum(1 for _ in p.iterdir())
        lines.insert(2, f"包含：{count} 项（不含子文件夹内容）")
    return "\n".join(lines)
