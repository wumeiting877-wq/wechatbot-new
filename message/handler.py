# -*- coding: utf-8 -*-
"""消息处理：handle_wxauto_message。行为与原 bot.py 保持一致。"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

from reminder_rules import looks_like_reminder
from message.bind import host
from message.pipeline import (
    MEDIA_MSG_TYPES,
    PipelineTrace,
    STEP_COMMAND,
    STEP_ENQUEUE,
    STEP_MEDIA,
    STEP_REMINDER,
    STEP_URL,
    summarize_trace_for_log,
)


def handle_wxauto_message(msg, who):
    """
    处理来自Wxauto的消息，包括可能的提醒、图片/表情、链接内容获取和常规聊天。
    """
    B = host()
    runtime = B.runtime
    logger = B.logger
    trace = PipelineTrace(chat_id=who, msgtype=getattr(msg, "type", None) or "text")
    try:
        if not runtime.is_accepting_work():
            trace.abort("stopped")
            return
        B.last_received_message_timestamp = time.time()
        username = who
        original_content = getattr(msg, "content", None) or getattr(msg, "text", None)
        msg_type = getattr(msg, "type", None)

        if not original_content:
            if msg_type in MEDIA_MSG_TYPES:
                original_content = ""
                logger.info(f"收到的 {msg_type} 消息没有文本内容，继续进入类型处理器。")
            else:
                logger.warning("收到的消息没有内容。")
                trace.abort("empty")
                return

        with trace.step(STEP_COMMAND) as step:
            try:
                if B._handle_text_command_if_any(original_content, username):
                    step.reason = "command_handled"
                    trace.abort("command")
                    _log_trace(runtime, trace)
                    return
                step.skip("not_a_command")
            except Exception as e:
                step.miss(str(e))
                logger.error(f"指令解析失败: {e}")

        B.on_user_message(username)

        with trace.step(STEP_REMINDER) as step:
            reminder_keywords_hit = looks_like_reminder(original_content)
            if B.ENABLE_REMINDERS and reminder_keywords_hit:
                logger.info(f"检测到可能的提醒请求，用户 {username}: {original_content}")
                reminder_set = B.try_parse_and_set_reminder(original_content, username)
                if reminder_set:
                    step.add_llm("assistant" if B.ENABLE_ASSISTANT_MODEL else "main", "reminder_parse")
                    logger.info(f"成功为用户 {username} 设置提醒，消息处理结束。")
                    trace.abort("reminder_set")
                    _log_trace(runtime, trace)
                    return
                step.miss("reminder_not_set")
            else:
                step.skip("no_reminder_keyword")

        img_path = None
        is_emoji = False
        processed_content = original_content

        with trace.step(STEP_MEDIA) as step:
            if msg.type in ("image",):
                if B.ENABLE_IMAGE_RECOGNITION:
                    img_path = None
                    for attempt in range(3):
                        try:
                            img_path = msg.download()
                            if img_path and os.path.exists(str(img_path)):
                                logger.info(f"图片下载成功 (第{attempt + 1}次尝试): {img_path}")
                                break
                            logger.warning(f"图片下载返回空路径 (第{attempt + 1}次尝试)")
                        except AttributeError as attr_err:
                            logger.warning(f"控件属性错误 (第{attempt + 1}次): {attr_err}")
                        except Exception as e:
                            logger.warning(f"图片下载异常 (第{attempt + 1}次): {e}")
                        if attempt < 2:
                            time.sleep(1.5)
                    if img_path:
                        is_emoji = False
                        processed_content = None
                        logger.info(f"检测到图片消息，准备识别: {img_path}")
                        step.reason = "image"
                    else:
                        logger.error("图片下载失败，已重试3次")
                        logger.error(
                            "\033[31m⚠️ 图片识别功能异常，请查看解决方案："
                            "https://s.apifox.cn/b2f07354-bce7-4959-a803-97ed82c508ff/7649190m0\033[0m"
                        )
                        step.miss("image_download_failed")
                else:
                    logger.info("检测到图片消息，但图片识别功能已禁用。")
                    step.skip("image_disabled")
            elif msg.type in ("emotion",):
                if B.ENABLE_EMOJI_RECOGNITION:
                    img_path = None
                    for attempt in range(3):
                        try:
                            img_path = msg.capture()
                            if img_path:
                                logger.info(f"表情截图成功 (第{attempt + 1}次尝试): {img_path}")
                                break
                            logger.warning(f"表情截图失败 (第{attempt + 1}次尝试)")
                        except Exception as e:
                            logger.warning(f"表情截图异常 (第{attempt + 1}次尝试): {e}")
                        if attempt < 2:
                            time.sleep(0.5)
                    if img_path:
                        is_emoji = True
                        processed_content = None
                        logger.info("检测到动画表情，准备截图识别...")
                        step.reason = "emotion"
                    else:
                        logger.error("表情截图失败，已重试3次")
                        step.miss("emoji_capture_failed")
                else:
                    logger.info("检测到动画表情，但表情识别功能已禁用。")
                    step.skip("emoji_disabled")
            else:
                step.skip("not_media")

            if img_path:
                logger.info(f"开始识别图片/表情 - 用户 {username}: {img_path}")
                recognized_text = B.recognize_image_with_moonshot(img_path, is_emoji=is_emoji)
                processed_content = recognized_text if recognized_text else ("[图片]" if not is_emoji else "[动画表情]")
                B.can_send_messages = True
                logger.info(f"图片/表情识别完成，结果: {processed_content}")
                step.add_llm("vision", "image_recognition")

        fetched_web_content = None
        with trace.step(STEP_URL) as step:
            if B.ENABLE_URL_FETCHING and processed_content is not None:
                url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
                urls_found = re.findall(url_pattern, original_content)
                if urls_found:
                    url_to_fetch = urls_found[0]
                    logger.info(f"检测到链接，用户 {username}，准备抓取: {url_to_fetch}")
                    fetched_web_content = B.fetch_and_extract_text(url_to_fetch)
                    if fetched_web_content:
                        logger.info(f"成功获取链接内容摘要 (长度 {len(fetched_web_content)})。")
                        processed_content = (
                            f"用户发送了消息：\"{original_content}\"\n"
                            f"其中包含的链接的主要内容摘要如下（可能不完整）：\n---\n{fetched_web_content}\n---\n"
                        )
                        step.reason = "fetched"
                    else:
                        logger.warning(f"未能从链接 {url_to_fetch} 提取有效文本内容。将按原始消息处理。")
                        step.miss("fetch_failed")
                else:
                    step.skip("no_url")
            else:
                step.skip("url_disabled_or_media")

        B.log_user_message_to_memory(username, processed_content)

        with trace.step(STEP_ENQUEUE) as step:
            if not runtime.is_accepting_work():
                step.skip("stopped")
                trace.abort("stopped")
                return
            if processed_content:
                current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
                content_with_time = f"[{current_time_str}] {processed_content}"
                logger.info(f"准备将处理后的消息加入队列 - 用户 {username}: {content_with_time[:150]}...")
                sender_name = username
                with B.queue_lock:
                    if username not in B.user_queues:
                        B.user_queues[username] = {
                            "messages": [content_with_time],
                            "sender_name": sender_name,
                            "username": username,
                            "last_message_time": time.time(),
                        }
                        logger.info(f"已为用户 {sender_name} 初始化消息队列并加入消息。")
                    else:
                        B.user_queues[username]["messages"].append(content_with_time)
                        B.user_queues[username]["last_message_time"] = time.time()
                        logger.info(
                            f"用户 {sender_name} 的消息已加入队列"
                            f"（当前 {len(B.user_queues[username]['messages'])} 条）并更新时间。"
                        )
            else:
                logger.warning(f"在处理后未找到用户 {username} 的可处理内容。原始消息: '{original_content}'")
                step.miss("no_processed_content")

    except Exception as e:
        B.can_send_messages = True
        logger.error(f"消息处理失败 (handle_wxauto_message): {str(e)}", exc_info=True)
        trace.abort(str(e))
    finally:
        _log_trace(runtime, trace)


def _log_trace(runtime, trace: PipelineTrace) -> None:
    try:
        runtime.log_event("PIPELINE", summarize_trace_for_log(trace), extra=trace.as_dict())
    except Exception:
        pass
