# -*- coding: utf-8 -*-
"""把 bot.py 进程里的宿主模块绑定给 message 包。

`python bot.py` 时宿主是 `__main__`，不能 `import bot`，否则会二次加载。
"""

from __future__ import annotations

_host = None


def bind_host(module) -> None:
    global _host
    _host = module


def host():
    if _host is None:
        raise RuntimeError("message 宿主未绑定，请在 bot.py 加载完成后调用 bind_host")
    return _host
