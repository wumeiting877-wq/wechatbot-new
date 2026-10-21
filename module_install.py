# -*- coding: utf-8 -*-
"""把独立模块里的函数装回 bot.py / config_editor.py 宿主命名空间。

搬迁时函数体仍使用原来的全局名（logger、chat_contexts 等），
安装时把 __globals__ 指到宿主模块，行为与未拆分时一致。
"""

from __future__ import annotations

import types
from typing import Iterable


def rebind(func, ns: dict):
    new = types.FunctionType(
        func.__code__,
        ns,
        func.__name__,
        func.__defaults__,
        func.__closure__,
    )
    new.__kwdefaults__ = func.__kwdefaults__
    new.__doc__ = func.__doc__
    new.__annotations__ = getattr(func, "__annotations__", {})
    new.__dict__.update(func.__dict__)
    return new


def install_exports(source_globals: dict, names: Iterable[str], target_module) -> None:
    ns = target_module.__dict__
    for name in names:
        func = source_globals[name]
        rebound = rebind(func, ns)
        setattr(target_module, name, rebound)
        source_globals[name] = rebound
