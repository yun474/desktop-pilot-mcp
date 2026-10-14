"""桌面操作专用的单线程执行器。

UI Automation 基于 COM，需要在固定线程中初始化后使用；同时把所有桌面操作串行化，
避免多个工具调用同时抢鼠标键盘。线程级 DPI 感知只作用于本线程，不影响 AstrBot 主进程的其他部分。
"""

from __future__ import annotations

import asyncio
import ctypes
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_PER_MONITOR_AWARE_V2 = -4

_local = threading.local()


def _init_thread() -> None:
    try:
        ctypes.windll.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(_PER_MONITOR_AWARE_V2))
    except Exception:
        pass
    import uiautomation as auto

    # 持有初始化器引用，线程存活期间保持 COM 已初始化
    _local.uia_init = auto.UIAutomationInitializerInThread(debug=False)


class DesktopWorker:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="desktop_pilot", initializer=_init_thread
        )

    async def run(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
