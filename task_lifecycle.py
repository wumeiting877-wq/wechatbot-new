# -*- coding: utf-8 -*-
"""Task 生命周期。只校验并提交状态迁移。"""

from __future__ import annotations

import logging

from task_store import (
    TASK_STATUS_DONE,
    TASK_STATUS_OPEN,
    TRANSITION_TRANSITIONED,
    TaskStore,
    TaskTransitionResult,
)

logger = logging.getLogger(__name__)


class TaskLifecycleService:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store

    def complete_task(self, conversation_id: str, task_id: str) -> TaskTransitionResult:
        result = self.task_store.transition_task_status(
            conversation_id,
            task_id,
            TASK_STATUS_OPEN,
            TASK_STATUS_DONE,
        )
        if result.status == TRANSITION_TRANSITIONED:
            logger.info(
                "Task lifecycle transitioned conversation_id=%s task_id=%s from_status=%s to_status=%s",
                result.conversation_id,
                result.task_id,
                result.from_status,
                result.to_status,
            )
        return result
