# -*- coding: utf-8 -*-
"""入站监听：message_listener。P0 走 identity / outbound / dedupe / trigger。"""

from __future__ import annotations

from bot_runtime import mask_secrets
from message.bind import host
from message.identity import inbound_from_wx_message
from message.pipeline import (
    MEDIA_MSG_TYPES,
    PipelineTrace,
    STEP_ADMIT,
    STEP_ATTR,
    STEP_EMPTY,
    STEP_LISTEN,
    STEP_NORMALIZE,
    classify_incoming_attr,
    is_empty_content_skippable,
    summarize_trace_for_log,
)
from message.trigger import NO_ACTION, REPLY

try:
    from topic_sidepath import try_enqueue_topic_sidepath
except Exception:  # Topic 模块异常不得阻止微信主链
    def try_enqueue_topic_sidepath(*_args, **_kwargs):
        return {"enqueued": False, "reason": "IMPORT_FAILED"}


def message_listener(msg, chat):
    B = host()
    runtime = B.runtime
    logger = B.logger
    who = chat.who
    msgtype = msg.type
    original_content = msg.content if isinstance(getattr(msg, "content", None), str) else (getattr(msg, "content", None) or "")
    sender = msg.sender
    msgattr = msg.attr
    inbound = inbound_from_wx_message(msg, chat, runtime.identity)
    trace = PipelineTrace(chat_id=who, sender=sender, msgtype=msgtype)
    logger.info(
        f'收到来自聊天窗口 "{who}" 中用户 "{sender}" 的原始消息 '
        f"(类型: {msgtype}, 属性: {msgattr}, sender_id={inbound.sender_id}, "
        f"sender_wxid={inbound.sender_wxid}, pid={inbound.platform_message_id}): "
        f"{mask_secrets(original_content[:100])}"
    )

    if not runtime.is_accepting_work():
        runtime.log_event("BOT", f"机器人状态 {runtime.state}，丢弃新消息")
        trace.abort("stopped")
        runtime.evaluate_inbound(inbound, listen_users=B.user_names)
        return

    with trace.step(STEP_ATTR) as step:
        attr_decision = classify_incoming_attr(msgattr, original_content)
        if attr_decision["reason"] == "self_tickle":
            step.skip("self_tickle")
            logger.info("检测到自己触发的拍一拍，已忽略。")
            trace.abort("self_tickle")
            return
        if attr_decision["action"] == "drop" and attr_decision["reason"] not in ("self_message",):
            step.skip(attr_decision["reason"])
            logger.info("非好友消息，已忽略。")
            trace.abort(attr_decision["reason"])
            return
        original_content = attr_decision["content"]
        inbound.content = original_content
        step.reason = attr_decision["reason"]

    is_group_chat = B.is_user_group_chat(who)
    with trace.step(STEP_ADMIT) as step:
        verdict = runtime.evaluate_inbound(
            inbound,
            listen_users=B.user_names,
            is_group=is_group_chat,
            accept_all=B.ACCEPT_ALL_GROUP_CHAT_MESSAGES,
            enable_at=B.ENABLE_GROUP_AT_REPLY,
            enable_keyword=B.ENABLE_GROUP_KEYWORD_REPLY,
            keywords=B.GROUP_KEYWORD_LIST,
            probability=B.GROUP_CHAT_RESPONSE_PROBABILITY,
            keyword_ignore_probability=B.GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY,
        )
        if verdict.get("action") == REPLY:
            try:
                from task_command_ingress import handle_task_command_turn
                if handle_task_command_turn(
                    inbound,
                    verdict,
                    runtime=runtime,
                    host=B,
                    chat_id=who,
                ):
                    step.reason = "task_command"
                    step.hit = True
                    trace.abort("task_command")
                    _log_trace(runtime, trace)
                    return
            except Exception:
                logger.exception("任务命令会话失败，回退原回复流程")
            try:
                from collaboration_query import handle_collaboration_route
                if handle_collaboration_route(
                    inbound,
                    verdict,
                    runtime=runtime,
                    host=B,
                    chat_id=who,
                ):
                    step.reason = "collaboration_route"
                    step.hit = True
                    trace.abort("collaboration_route")
                    _log_trace(runtime, trace)
                    return
            except Exception:
                logger.exception("协作查询路由失败，回退原回复流程")
        try:
            try_enqueue_topic_sidepath(inbound, verdict, runtime=runtime)
        except Exception:
            pass
        if verdict.get("action") != REPLY:
            step.skip(verdict.get("reason") or "no_action")
            if verdict.get("identity") == "SELF" or "outbound" in str(verdict.get("reason") or ""):
                B.bot_last_sent_msg[who] = msg
            trace.abort(verdict.get("reason") or NO_ACTION)
            _log_trace(runtime, trace)
            return
        runtime.note_received(who, original_content)
        step.reason = verdict.get("reason") or "ok"

    with trace.step(STEP_NORMALIZE) as step:
        if msgtype == "voice":
            voicetext = msg.to_text()
            original_content = f"[语音消息]: {voicetext}"
            inbound.content = original_content
            step.reason = "voice"
        elif msgtype == "link":
            cardurl = msg.get_url()
            original_content = f"[卡片链接]: {cardurl}"
            inbound.content = original_content
            step.reason = "link"
        elif msgtype == "quote":
            quoted_msg = msg.quote_content
            if quoted_msg:
                original_content = f"[引用<{quoted_msg}>消息]: {msg.content}"
            else:
                original_content = msg.content
            inbound.content = original_content
            step.reason = "quote"
        elif msgtype == "merge":
            original_content = _expand_merge_message(B, msg, original_content)
            inbound.content = original_content
            step.reason = "merge"
        else:
            step.skip("plain_text")

    with trace.step(STEP_EMPTY) as step:
        if is_empty_content_skippable(original_content, msgtype):
            step.skip("empty")
            logger.info("消息内容为空，已忽略。")
            trace.abort("empty")
            _log_trace(runtime, trace)
            return
        if not original_content and msgtype in MEDIA_MSG_TYPES:
            logger.info(f"收到 {msgtype} 消息，文本内容为空，继续进入对应类型处理。")
            original_content = ""
            step.reason = "media_empty_ok"
        else:
            step.skip("has_content")

    extra = (verdict.get("extra") or {})
    content_for_handler = extra.get("content_for_handler") or original_content
    with trace.step(STEP_LISTEN) as step:
        step.reason = extra.get("listen_reason") or verdict.get("reason") or "reply"
        step.hit = True
        if is_group_chat:
            logger.info(f"群聊 '{who}' 触发结果：{step.reason}")
        else:
            logger.info(f"收到来自监听列表用户 {who} 的个人私聊消息，准备处理。")

    msg.content = content_for_handler
    logger.info(f'最终准备处理消息 from chat "{who}" by sender "{sender}": {msg.content[:100]}')
    runtime.log_event("BOT", f"规则命中 REPLY，准备进入回复流程。会话：{who}")

    if not is_group_chat:
        B.user_last_msg[who] = msg
        logger.debug(f"已保存用户 {who} 的最后消息对象")

    is_animation_emoji_in_original = msgtype == "emotion"
    if is_animation_emoji_in_original and B.ENABLE_EMOJI_RECOGNITION:
        B.handle_emoji_message(msg, who)
    else:
        B.handle_wxauto_message(msg, who)

    _log_trace(runtime, trace)


def _expand_merge_message(B, msg, original_content: str) -> str:
    logger = B.logger
    logger.info("收到合并转发消息，开始处理")
    mergecontent = msg.get_messages()
    logger.info("收到合并转发消息，处理完成")
    if isinstance(mergecontent, list):
        merged_text_lines = []
        for item in mergecontent:
            if isinstance(item, list) and len(item) == 3:
                sender, content, timestamp = item
                if hasattr(content, "suffix") and str(content.suffix).lower() in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                    content = _maybe_recognize_image(B, str(content))
                elif isinstance(content, str) and content.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp")):
                    content = _maybe_recognize_image(B, content)
                merged_text_lines.append(f"[{timestamp}] {sender}: {content}")
            else:
                merged_text_lines.append(str(item))
        merged_text = "\n".join(merged_text_lines)
        return f"[合并转发消息]:\n{merged_text}"
    return f"[合并转发消息]: {mergecontent}"


def _maybe_recognize_image(B, image_path: str) -> str:
    logger = B.logger
    if not B.ENABLE_IMAGE_RECOGNITION:
        return "[图片]"
    original_can_send_messages = B.can_send_messages
    try:
        logger.info(f"开始识别图片: {image_path}")
        content = B.recognize_image_with_moonshot(image_path, is_emoji=False)
        if content:
            logger.info(f"图片识别成功: {content}")
            recognized = f"[图片识别结果]: {content}"
        else:
            recognized = "[图片识别结果]: 无法识别图片内容"
        B.can_send_messages = original_can_send_messages
        return recognized
    except Exception as e:
        logger.error(f"图片识别失败: {e}")
        B.can_send_messages = True
        return "[图片识别失败]"


def _log_trace(runtime, trace: PipelineTrace) -> None:
    try:
        runtime.log_event("PIPELINE", summarize_trace_for_log(trace), extra=trace.as_dict())
    except Exception:
        pass
