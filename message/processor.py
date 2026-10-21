# -*- coding: utf-8 -*-
"""队列合并与主回复：check_inactive_users / process_user_messages。"""

from __future__ import annotations

import time

from message.bind import host
from message.pipeline import (
    PipelineTrace,
    STEP_MAIN_LLM,
    STEP_ONLINE,
    summarize_trace_for_log,
)


def check_inactive_users():
    B = host()
    runtime = B.runtime
    while True:
        if runtime.is_send_blocked() or not runtime.is_accepting_work():
            with B.queue_lock:
                if B.user_queues:
                    B.user_queues.clear()
                    runtime.log_event("BOT", "停止中：已清空待处理消息队列")
            _clear_pending_agent_replies(runtime)
            time.sleep(0.2)
            continue
        current_time = time.time()
        inactive_users = []
        with B.queue_lock:
            for username, user_data in B.user_queues.items():
                last_time = user_data.get("last_message_time", 0)
                if (
                    current_time - last_time > B.QUEUE_WAITING_TIME
                    and B.can_send_messages
                    and not B.is_sending_message
                    and not runtime.session_busy(username)
                ):
                    inactive_users.append(username)

        for username in inactive_users:
            process_user_messages(username)

        _flush_idle_agent_replies(runtime)
        time.sleep(1)


def process_user_messages(user_id):
    """处理指定用户的消息队列，包括可能的联网搜索。"""
    B = host()
    runtime = B.runtime
    logger = B.logger
    trace = PipelineTrace(chat_id=user_id, msgtype="merged")

    if runtime.is_send_blocked() or not runtime.is_accepting_work():
        return
    if runtime.session_busy(user_id):
        runtime.log_event("BOT", f"会话锁：{user_id} 已有回复任务执行中，本轮保留队列")
        return
    allowed, rate_reason = runtime.allow_reply(user_id)
    if not allowed:
        runtime.log_event("BOT", rate_reason)
        return
    if not runtime.try_acquire_session(user_id):
        runtime.log_event("BOT", f"会话锁：{user_id} 并发冲突，本轮保留队列")
        return

    try:
        with B.queue_lock:
            if user_id not in B.user_queues:
                runtime.release_session(user_id)
                return
            user_data = B.user_queues.pop(user_id)
            messages = user_data["messages"]
            sender_name = user_data["sender_name"]
            username = user_data["username"]
    except Exception:
        runtime.release_session(user_id)
        raise

    merged_message = " ".join(messages)
    logger.info(f"开始处理用户 '{sender_name}' (ID: {user_id}) 的合并消息: {merged_message[:100]}...")

    is_auto_message = "触发主动发消息：" in merged_message
    reply = None
    online_info = None

    try:
        with trace.step(STEP_ONLINE) as step:
            if B.ENABLE_ONLINE_API:
                search_content = B.needs_online_search(merged_message, user_id)
                if search_content:
                    step.add_llm("assistant", "online_detect")
                    logger.info(f"尝试为用户 {user_id} 执行在线搜索...")
                    merged_message = (
                        f"用户原始信息：\n{merged_message}\n\n需要进行联网搜索的信息：\n{search_content}"
                    )
                    online_info = B.get_online_model_response(merged_message, user_id)
                    if online_info:
                        step.add_llm("online", "online_search")
                        logger.info(f"成功获取在线信息，为用户 {user_id} 准备最终回复...")
                        final_prompt = f"""
用户的原始问题是：
"{merged_message}"

根据以下联网搜索到的参考信息：
---
{online_info}
---

请结合你的角色设定，以自然的方式回答用户的原始问题。请直接给出回答内容，不要提及你是联网搜索的。
"""
                        reply = B.get_deepseek_response(final_prompt, user_id, store_context=True)
                        step.add_llm("main", "main_chat")
                    else:
                        logger.warning(f"在线搜索未能获取有效信息，用户: {user_id}。将按常规流程处理。")
                        step.miss("online_empty")
                else:
                    step.skip("online_not_needed")
            else:
                step.skip("online_disabled")

        if runtime.is_send_blocked() or runtime.llm_aborted():
            runtime.log_event("AI", f"停止中：已取消对 {user_id} 的 AI 请求")
            trace.abort("stopped_before_llm")
            return

        with trace.step(STEP_MAIN_LLM) as step:
            if reply is None:
                logger.info(f"为用户 {user_id} 执行常规回复（无联网信息）。")
                prompt_extra = {}
                try:
                    loader = getattr(B, "load_chat_prompt", None)
                    if callable(loader):
                        binding = loader(user_id)
                        prompt_extra = {
                            "conversation_id": binding.conversation_id,
                            "agent_config_id": binding.agent_config_id,
                            "prompt_name": binding.prompt_name,
                            "prompt_hash": binding.prompt_hash,
                        }
                except Exception:
                    prompt_extra = {}
                runtime.log_event("AI", f"AI 请求：主语言模型，会话 {user_id}", extra=prompt_extra or None)
                reply = B.get_deepseek_response(merged_message, user_id, store_context=True)
                step.add_llm("main", "main_chat")
            else:
                step.skip("already_replied_via_online")

        if runtime.is_send_blocked() or runtime.llm_aborted() or not runtime.is_operational():
            runtime.log_event("AI", f"停止中：已丢弃对 {user_id} 的 AI 响应")
            trace.abort("stopped_after_llm")
            return

        if reply:
            if "</think>" in reply:
                reply = reply.split("</think>", 1)[1].strip()
            if "## 记忆片段" not in reply:
                B.send_reply(user_id, sender_name, username, merged_message, reply)
            else:
                logger.info(f"回复包含记忆片段标记，已屏蔽发送给用户 {user_id}。")
        else:
            logger.error(f"未能为用户 {user_id} 生成任何回复。")

    except Exception as e:
        if is_auto_message:
            logger.error(f"主动消息处理失败 (用户: {user_id}): {str(e)}")
            logger.info(f"主动消息API调用失败，已静默处理，不发送错误提示给用户 {user_id}")
        else:
            logger.error(f"用户消息处理失败 (用户: {user_id}): {str(e)}")
            runtime.note_error(f"用户消息处理失败 (会话: {user_id}): {str(e)}")
            raise
    finally:
        runtime.release_session(user_id)
        notify_session_released = _notify_session_released()
        if notify_session_released is not None:
            try:
                notify_session_released(runtime, user_id)
            except Exception:
                pass
        _log_trace(runtime, trace)


def _notify_session_released():
    try:
        from agent_reply_delivery import notify_session_released
    except Exception:
        return None
    return notify_session_released


def _clear_pending_agent_replies(runtime) -> None:
    try:
        from agent_reply_delivery import clear_pending
        clear_pending(runtime, reason="stop")
    except Exception:
        pass


def _flush_idle_agent_replies(runtime) -> None:
    try:
        from agent_reply_delivery import flush_idle_pending
        flush_idle_pending(runtime)
    except Exception:
        pass


def _log_trace(runtime, trace: PipelineTrace) -> None:
    try:
        runtime.log_event("PIPELINE", summarize_trace_for_log(trace), extra=trace.as_dict())
    except Exception:
        pass
