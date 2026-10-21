# -*- coding: utf-8 -*-
"""本地文件的带锁原子读写。Prompt / 记忆 / 提醒 / 审计都走这里。"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any, Callable, Optional

from filelock import FileLock

logger = logging.getLogger(__name__)


def lock_path_for(path: str) -> str:
    return f"{path}.lock"


def atomic_write_text(path: str, content: str, encoding: str = "utf-8") -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    lock = FileLock(lock_path_for(path))
    with lock:
        try:
            with open(tmp, "w", encoding=encoding, newline="") as f:
                f.write(content if content is not None else "")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def atomic_write_json(path: str, data: Any, indent: int = 4) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    atomic_write_text(path, text)


def read_json(path: str, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    lock = FileLock(lock_path_for(path))
    with lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取 JSON 失败 %s: %s", path, exc)
            return default


def update_json(path: str, updater: Callable[[Any], Any], default: Any = None) -> Any:
    if default is None:
        default = {}
    lock = FileLock(lock_path_for(path))
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with lock:
        data = default
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = default
        data = updater(data)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return data
