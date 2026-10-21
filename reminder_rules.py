# -*- coding: utf-8 -*-
"""提醒意图低成本规则预筛。普通聊天不得先打一次提醒模型。"""

from __future__ import annotations

REMINDER_KEYWORDS = (
    "每日", "每天", "提醒", "提醒我", "定时", "分钟后", "小时后",
    "计时", "闹钟", "通知我", "叫我", "提醒一下", "倒计时",
    "稍后提醒", "稍后通知", "提醒时间", "设置提醒", "喊我",
    "明天", "后天", "每周",
)


def looks_like_reminder(text: str) -> bool:
    content = (text or "").strip()
    if not content:
        return False
    return any(keyword in content for keyword in REMINDER_KEYWORDS)
