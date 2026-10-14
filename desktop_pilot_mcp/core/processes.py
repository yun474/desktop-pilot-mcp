"""进程查看与结束（psutil）。"""

from __future__ import annotations

import os
import time

import psutil

# 结束这些进程会导致系统崩溃或注销，拒绝操作
_PROTECTED = {"system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "lsass.exe",
              "services.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe", "registry", "memory compression"}


def list_processes(name: str = "", sort_by: str = "memory", limit: int = 30) -> str:
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        pname = p.info["name"] or ""
        if name and name.lower() not in pname.lower():
            continue
        try:
            p.cpu_percent(None)  # 第一次调用只建立基准
        except psutil.Error:
            continue
        procs.append(p)
    # CPU 占用需要两次采样之间的间隔
    if sort_by == "cpu":
        time.sleep(0.5)
    rows = []
    for p in procs:
        try:
            cpu = p.cpu_percent(None) / psutil.cpu_count() if sort_by == "cpu" else 0.0
            mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
        except psutil.Error:
            continue
        rows.append((p.pid, p.info["name"] or "?", mem, cpu))
    key = {"cpu": lambda r: -r[3], "name": lambda r: r[1].lower()}.get(sort_by, lambda r: -r[2])
    rows.sort(key=key)
    limit = max(1, min(limit, 200))
    lines = [f"共 {len(rows)} 个进程{f'（名称包含「{name}」）' if name else ''}，按{_SORT_NAMES.get(sort_by, '内存')}排序显示前 {min(limit, len(rows))} 个："]
    for pid, pname, mem, cpu in rows[:limit]:
        cpu_text = f"  CPU {cpu:.1f}%" if sort_by == "cpu" else ""
        lines.append(f"PID {pid}  {pname}  内存 {mem / 1048576:.0f} MB{cpu_text}")
    return "\n".join(lines)


_SORT_NAMES = {"memory": "内存", "cpu": "CPU", "name": "名称"}


def kill(pid: int | None = None, name: str = "", force: bool = False) -> str:
    if pid is None and not name.strip():
        raise ValueError("请提供进程 PID 或进程名")
    if pid is not None:
        try:
            targets = [psutil.Process(pid)]
        except psutil.NoSuchProcess:
            raise LookupError(f"PID {pid} 对应的进程不存在") from None
    else:
        key = name.strip().lower()
        key_exe = key if key.endswith(".exe") else key + ".exe"
        targets = [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() in (key, key_exe)]
        if not targets:
            raise LookupError(f"没有找到名为「{name}」的进程")
    me = os.getpid()
    done, failed = [], []
    for p in targets:
        try:
            pname = p.name()
            if p.pid == me or pname.lower() in _PROTECTED:
                failed.append(f"{pname}（PID {p.pid}）：系统关键进程或本服务自身，拒绝结束")
                continue
            p.kill() if force else p.terminate()
            done.append(f"{pname}（PID {p.pid}）")
        except psutil.AccessDenied:
            failed.append(f"PID {p.pid}：没有权限（可能需要管理员身份运行本服务）")
        except psutil.NoSuchProcess:
            failed.append(f"PID {p.pid}：进程已不存在")
    lines = []
    if done:
        lines.append(f"已{'强制' if force else ''}结束：" + "、".join(done))
    if failed:
        lines.append("未能结束：\n" + "\n".join(failed))
    return "\n".join(lines)
