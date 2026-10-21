# -*- coding: utf-8 -*-
"""消息入站 / 处理流水线。

子模块按需导入，避免 bot_runtime ↔ listener 循环依赖。
"""

from message.bind import bind_host, host

__all__ = [
    "bind_host",
    "host",
]
