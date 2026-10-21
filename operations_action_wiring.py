# -*- coding: utf-8 -*-
"""把人工重试接到 P6 已封板的 retry capability。

enabled 只读现有开关函数。这里不把模块常量改成 true。
"""

from __future__ import annotations

from typing import Any

from decision_engine import DecisionEngine
from decision_sidepath import DecisionSidepath, is_decision_engine_enabled
from decision_store import DecisionStore
from downstream_retry import DownstreamRetryService
from risk_engine import RiskEngine
from risk_sidepath import RiskSidepath, is_risk_engine_enabled
from risk_store import RiskStore
from task_engine import TaskEngine
from task_sidepath import TaskSidepath, is_task_engine_enabled
from task_store import TaskStore
from topic_retry import TopicRetryService
from topic_sidepath import TopicSidepath
from topic_store import TopicStore

_DRAIN_SECONDS = 30


class TopicRetryBinding:
    """一次请求一套旁路。等既有 fan-out 队列排空后再关闭，避免把下游任务丢掉。"""

    def __init__(self, root_dir: str, runtime: Any = None):
        self.task_path = TaskSidepath(root_dir=root_dir, maxsize=8)
        self.decision_path = DecisionSidepath(root_dir=root_dir, maxsize=8)
        self.risk_path = RiskSidepath(root_dir=root_dir, maxsize=8)
        self.sidepath = TopicSidepath(
            root_dir=root_dir,
            maxsize=8,
            task_sidepath=self.task_path,
            decision_sidepath=self.decision_path,
            risk_sidepath=self.risk_path,
        )
        self.service = TopicRetryService(
            topic_sidepath=self.sidepath,
            runtime=runtime,
        )

    def retry_topic(self, conversation_id: str, message_id: str, *, version: int = 0, runtime: Any = None):
        outcome = self.service.retry_topic(
            conversation_id,
            message_id,
            version=version,
            runtime=runtime,
        )
        self.sidepath.wait_idle(_DRAIN_SECONDS)
        self.task_path.wait_idle(_DRAIN_SECONDS)
        self.decision_path.wait_idle(_DRAIN_SECONDS)
        self.risk_path.wait_idle(_DRAIN_SECONDS)
        return outcome

    def close(self) -> None:
        try:
            self.sidepath.shutdown()
        except Exception:
            return


class DownstreamRetryBinding:
    def __init__(self, root_dir: str, runtime: Any = None):
        topic_store = TopicStore(root_dir)
        task_store = TaskStore(root_dir, topic_store=topic_store)
        decision_store = DecisionStore(root_dir, topic_store=topic_store)
        risk_store = RiskStore(root_dir, topic_store=topic_store, task_store=task_store)
        self.service = DownstreamRetryService(
            topic_store=topic_store,
            task_engine=TaskEngine(
                task_store,
                topic_store,
                root_dir=root_dir,
                enabled=is_task_engine_enabled(),
            ),
            decision_engine=DecisionEngine(
                decision_store,
                topic_store,
                root_dir=root_dir,
                enabled=is_decision_engine_enabled(),
            ),
            risk_engine=RiskEngine(
                risk_store,
                topic_store,
                task_store=task_store,
                root_dir=root_dir,
                enabled=is_risk_engine_enabled(),
            ),
            runtime=runtime,
        )

    def retry_downstream(
        self,
        engine: str,
        conversation_id: str,
        message_id: str,
        topic_id: str = "",
        *,
        version: int = 0,
        runtime: Any = None,
    ):
        return self.service.retry_downstream(
            engine,
            conversation_id,
            message_id,
            topic_id,
            version=version,
            runtime=runtime,
        )

    def close(self) -> None:
        return None
