# -*- coding: utf-8 -*-
"""群聊触发规则：@、关键词、全局接收、回复频率。"""

from __future__ import annotations

import random
import re
from typing import Callable, Iterable, Optional


def detect_group_at(content: str, robot_name: str) -> tuple[bool, str]:
    text = content or ""
    name = (robot_name or "").strip()
    if not name:
        return False, text
    unicode_at_pattern = f"@{re.escape(name)}\u2005"
    space_at_pattern = f"@{re.escape(name)} "
    exact_at_string = f"@{name}"
    if re.search(unicode_at_pattern, text):
        return True, re.sub(unicode_at_pattern, "", text, count=1).strip()
    if re.search(space_at_pattern, text):
        return True, re.sub(space_at_pattern, "", text, count=1).strip()
    if text.strip() == exact_at_string:
        return True, ""
    return False, text


def detect_group_keyword(content: str, keywords: Iterable[str]) -> bool:
    text = content or ""
    return any(keyword and keyword in text for keyword in keywords)


def evaluate_group_trigger(
    content: str,
    robot_name: str = "",
    accept_all: bool = False,
    enable_at: bool = True,
    enable_keyword: bool = False,
    keywords: Optional[Iterable[str]] = None,
    probability: int = 100,
    keyword_ignore_probability: bool = True,
    rng: Optional[Callable[[int, int], int]] = None,
) -> dict:
    """返回是否处理、原因、去掉 @ 后的文本。"""
    processed = content or ""
    at_triggered = False
    keyword_triggered = False
    roll = rng or random.randint

    if not accept_all and enable_at and robot_name:
        at_triggered, processed = detect_group_at(content, robot_name)
    if enable_keyword:
        keyword_triggered = detect_group_keyword(processed, keywords or [])

    basic = accept_all or at_triggered or keyword_triggered
    if not basic:
        return {
            "should_process": False,
            "reason": "未命中 @、关键词或全局接收",
            "at_triggered": at_triggered,
            "keyword_triggered": keyword_triggered,
            "processed_content": processed,
        }

    if keyword_triggered and keyword_ignore_probability:
        return {
            "should_process": True,
            "reason": "关键词触发且忽略回复频率",
            "at_triggered": at_triggered,
            "keyword_triggered": keyword_triggered,
            "processed_content": processed,
        }

    chance = max(0, min(100, int(probability)))
    if roll(1, 100) <= chance:
        return {
            "should_process": True,
            "reason": f"通过群聊回复频率 {chance}%",
            "at_triggered": at_triggered,
            "keyword_triggered": keyword_triggered,
            "processed_content": processed,
        }
    return {
        "should_process": False,
        "reason": f"未通过群聊回复频率 {chance}%",
        "at_triggered": at_triggered,
        "keyword_triggered": keyword_triggered,
        "processed_content": processed,
    }
