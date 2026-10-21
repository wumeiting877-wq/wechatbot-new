# -*- coding: utf-8 -*-
"""主模型 / 辅助模型 / 识图 / 联网。函数在 bot 宿主安装后使用其全局命名空间。"""

from __future__ import annotations

import re
from typing import Optional

from module_install import install_exports

EXPORTS = (
    "get_deepseek_response",
    "strip_before_thought_tags",
    "_usage_tokens",
    "_llm_purpose",
    "call_chat_api_with_retry",
    "get_assistant_response",
    "call_assistant_api_with_retry",
    "recognize_image_with_moonshot",
    "needs_online_search",
    "get_online_model_response",
    "call_narrow_completion",
    "get_extractor_response",
    "_extractor_log_purpose",
    "_invoke_extractor",
    "_extractor_choice_text",
    "_finish_extractor_text",
    "_looks_like_extractor_json",
    "_resolver_extractor_client",
)


def install_into(module) -> None:
    install_exports(globals(), EXPORTS, module)


def get_deepseek_response(message, user_id, store_context=True, is_summary=False):
    """
    从语言模型获取响应，确保正确的上下文处理，并持久化上下文。

    参数:
        message (str): 用户的消息或系统提示词（用于工具调用）。
        user_id (str): 用户或系统组件的标识符。
        store_context (bool): 是否将此交互存储到聊天上下文中。
                              对于工具调用（如解析或总结），设置为 False。
    """
    if runtime.is_send_blocked() or runtime.llm_aborted():
        logger.warning(f"机器人已停止，取消对 {user_id} 的 AI 请求。")
        return None
    try:
        # 仅在外部改过文件时重载，默认走内存
        load_chat_contexts()
        
        logger.info(f"调用 Chat API - ID: {user_id}, 是否存储上下文: {store_context}, 消息: {mask_secrets(message[:100])}...")

        messages_to_send = []
        context_limit = MAX_GROUPS * 2  # 最大消息总数（不包括系统消息）

        if store_context:
            # --- 处理需要上下文的常规聊天消息 ---
            # 1. 获取该用户的系统提示词
            try:
                user_prompt = get_user_prompt(user_id)
                messages_to_send.append({"role": "system", "content": user_prompt})
                load_prompt = globals().get("load_chat_prompt")
                if callable(load_prompt):
                    binding = load_prompt(user_id)
                    runtime.log_event(
                        "AI",
                        "CHAT_PROMPT conversation_id=%s agent_config_id=%s prompt_name=%s prompt_hash=%s"
                        % (
                            binding.conversation_id,
                            binding.agent_config_id,
                            binding.prompt_name,
                            binding.prompt_hash,
                        ),
                        extra={
                            "conversation_id": binding.conversation_id,
                            "agent_config_id": binding.agent_config_id,
                            "prompt_name": binding.prompt_name,
                            "prompt_hash": binding.prompt_hash,
                        },
                    )
            except Exception as e:
                import agent_store
                if isinstance(e, agent_store.PromptResolveError):
                    logger.error(
                        "%s user_id=%s detail=%s",
                        e.code,
                        user_id,
                        e.detail,
                    )
                    runtime.log_event(
                        "ERROR",
                        "%s: %s" % (e.code, e.detail),
                        extra={
                            "code": e.code,
                            "user_id": user_id,
                            **(e.extra or {}),
                        },
                    )
                    return agent_store.AGENT_UNAVAILABLE_USER_MESSAGE
                if isinstance(e, FileNotFoundError):
                    logger.error("PROMPT_FILE_NOT_FOUND user_id=%s detail=%s", user_id, e)
                    runtime.log_event("ERROR", "PROMPT_FILE_NOT_FOUND: %s" % e)
                    return agent_store.AGENT_UNAVAILABLE_USER_MESSAGE
                raise

            # 2. 管理并检索聊天历史记录
            with queue_lock: # 确保对 chat_contexts 的访问是线程安全的
                if user_id not in chat_contexts:
                    chat_contexts[user_id] = []

                # 在添加当前消息之前获取现有历史记录
                history = list(chat_contexts.get(user_id, []))  # 获取副本

                # 如果历史记录超过限制，则进行裁剪
                if len(history) > context_limit:
                    history = history[-context_limit:]  # 保留最近的消息

                # 将历史消息添加到 API 请求列表中
                messages_to_send.extend(history)

                # 3. 将当前用户消息添加到 API 请求列表中
                messages_to_send.append({"role": "user", "content": message})

                # 4. 在准备 API 调用后更新持久上下文
                # 将用户消息添加到持久存储中
                chat_contexts[user_id].append({"role": "user", "content": message})
                # 如果需要，裁剪持久存储（在助手回复后会再次裁剪）
                if len(chat_contexts[user_id]) > context_limit + 1:  # +1 因为刚刚添加了用户消息
                    chat_contexts[user_id] = chat_contexts[user_id][-(context_limit + 1):]
                
                # 保存上下文到文件
                save_chat_contexts() # 在用户消息添加后保存一次

        else:
            # --- 处理工具调用（如提醒解析、总结） ---
            messages_to_send.append({"role": "user", "content": message})
            logger.info(f"工具调用 (store_context=False)，ID: {user_id}。仅发送提供的消息。")

        # --- 调用 API ---
        reply = call_chat_api_with_retry(messages_to_send, user_id, is_summary=is_summary)

        # --- 如果需要，存储助手回复到上下文中 ---
        if store_context:
            with queue_lock: # 再次获取锁来更新和保存
                if user_id not in chat_contexts:
                   chat_contexts[user_id] = []  # 安全初始化 (理论上此时应已存在)

                chat_contexts[user_id].append({"role": "assistant", "content": reply})

                if len(chat_contexts[user_id]) > context_limit:
                    chat_contexts[user_id] = chat_contexts[user_id][-context_limit:]
                
                # 保存上下文到文件
                save_chat_contexts() # 在助手回复添加后再次保存
        
        return reply

    except LlmApiError as e:
        logger.error(f"Chat 调用失败 (ID: {user_id}): code={e.code} detail={mask_secrets(e.log_detail)}")
        return e.user_message
    except Exception as e:
        logger.error(f"Chat 调用失败 (ID: {user_id}): {mask_secrets(str(e))}", exc_info=True)
        return "AI 服务暂时不可用，请稍后重试"



def strip_before_thought_tags(text):
    # 匹配并截取 </thought> 或 </think> 后面的内容
    if text is None:
        return None
    match = re.search(r'(?:</thought>|</think>)([\s\S]*)', text)
    if match:
        return match.group(1)
    else:
        return text



def _usage_tokens(response) -> tuple:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)



def _llm_purpose(user_id, is_summary=False, store_context=True) -> str:
    uid = str(user_id or "")
    if is_summary or uid in ("system", "memory_summary", "memory_importance"):
        return "summary"
    if uid.startswith("reminder_parser"):
        return "reminder_parse"
    if uid.startswith("online_detection"):
        return "online_detect"
    if uid == "emoji_detection":
        return "emoji_detect"
    if not store_context:
        return "tool"
    return "main_chat"



def call_chat_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """
    调用 Chat API 并在第一次失败或返回空结果时重试。

    参数:
        messages_to_send (list): 要发送给 API 的消息列表。
        user_id (str): 用户或系统组件的标识符。
        max_retries (int): 最大重试次数。

    返回:
        str: API 返回的文本回复。
    """
    started = time.perf_counter()
    purpose = _llm_purpose(user_id, is_summary=is_summary, store_context=not is_summary)
    if _is_base_url_untrusted(DEEPSEEK_BASE_URL):
        logger.error("当前 API 服务商不受信任，已拒绝请求")
        raise classify_api_error(RuntimeError("untrusted provider"))

    attempt = 0
    last_error = None
    while attempt <= max_retries:
        if runtime.llm_aborted() or runtime.is_send_blocked():
            logger.warning(f"停止中：取消对 {user_id} 的 Chat API 调用")
            return None
        try:
            logger.debug(f"发送给 API 的消息 (ID: {user_id}): {messages_to_send}")

            response = client.chat.completions.create(
                model=MODEL,
                messages=messages_to_send,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKEN,
                stream=False
            )

            if response.choices:
                # 检查API是否返回了空的消息内容
                message_content = response.choices[0].message.content
                if message_content is None:
                    logger.error(f"\033[31mAPI返回了空的信息，可能是因为触发了安全检查机制，请修改Prompt并清空上下文再试 (ID: {user_id})\033[0m")
                    logger.error(f"错误请求消息体模型: {MODEL}")
                    logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
                    logger.error(f"完整响应对象: {response}")
                else:
                    content = message_content.strip()
                    if content and "[image]" not in content and content != "ext":
                        filtered_content = strip_before_thought_tags(content)
                        if filtered_content:
                            prompt_tokens, completion_tokens = _usage_tokens(response)
                            runtime.note_llm_call(
                                purpose,
                                "main",
                                (time.perf_counter() - started) * 1000,
                                True,
                                "",
                                prompt_tokens,
                                completion_tokens,
                            )
                            return filtered_content
            else:
                # 记录错误日志 - 无选择项
                logger.error(f"\033[31mAPI返回了空的选择项 (ID: {user_id})\033[0m")
                logger.error(f"错误请求消息体模型: {MODEL}")
                logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
                logger.error(f"完整响应对象: {response}")

            # 如果到这里说明内容为空或过滤后为空
            if response.choices and response.choices[0].message.content is not None:
                logger.error(f"\033[31mAPI返回了空的内容或内容被过滤 (ID: {user_id})\033[0m")
            logger.error(f"错误请求消息体模型: {MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))

        except Exception as e:
            logger.error(f"错误请求消息体: {MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            classified = classify_api_error(e)
            logger.error(
                f"自动重试：第 {attempt + 1} 次调用 {MODEL}失败 (ID: {user_id}) "
                f"code={classified.code} status={classified.status_code} detail={mask_secrets(classified.log_detail)}",
                exc_info=False,
            )
            last_error = classified
            if classified.code == "CONTENT_FILTER" and ENABLE_SENSITIVE_CONTENT_CLEARING:
                logger.warning(f"已开启敏感词自动清除上下文功能，开始清除用户 {user_id} 的聊天上下文和临时记忆")
                clear_chat_context(user_id)
                clear_memory_temp_files(user_id)
                break
            if not is_retryable(classified):
                break

        attempt += 1

    error = last_error or LlmApiError("UNKNOWN_ERROR", "AI 服务暂时不可用，请稍后重试", "retries exhausted")
    runtime.log_event("LLM_FAILED", f"{error.code}: {mask_secrets(error.log_detail)}")
    runtime.note_llm_call(
        purpose,
        "main",
        (time.perf_counter() - started) * 1000,
        False,
        error.code,
    )
    raise error


def get_assistant_response(message, user_id, is_summary=False, allow_main_fallback=False):
    """
    从辅助模型 API 获取响应，专用于判断型任务（表情、联网、提醒解析等）。
    分类任务默认不回退主模型，避免普通消息多打一次 LLM。
    """
    if not assistant_client:
        if allow_main_fallback:
            logger.warning(f"辅助模型客户端未初始化，回退使用主模型。用户ID: {user_id}")
            return get_deepseek_response(message, user_id, store_context=False, is_summary=is_summary)
        logger.info(f"辅助模型未就绪，跳过该判断。用户ID: {user_id}")
        return None
    
    try:
        logger.info(f"调用辅助模型 API - ID: {user_id}, 消息: {mask_secrets(message[:100])}...")
        
        messages_to_send = [{"role": "user", "content": message}]
        
        reply = call_assistant_api_with_retry(messages_to_send, user_id, is_summary=is_summary)
        
        return reply

    except Exception as e:
        logger.error(f"辅助模型调用失败 (ID: {user_id}): {mask_secrets(str(e))}", exc_info=True)
        if allow_main_fallback:
            logger.warning(f"辅助模型调用失败，回退使用主模型。用户ID: {user_id}")
            return get_deepseek_response(message, user_id, store_context=False, is_summary=is_summary)
        return None


def call_assistant_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """
    调用辅助模型 API 并在第一次失败或返回空结果时重试。

    参数:
        messages_to_send (list): 要发送给辅助模型的消息列表。
        user_id (str): 用户或系统组件的标识符。
        max_retries (int): 最大重试次数。

    返回:
        str: 辅助模型返回的文本回复。
    """
    started = time.perf_counter()
    purpose = _llm_purpose(user_id, is_summary=is_summary, store_context=False)
    attempt = 0
    while attempt <= max_retries:
        if runtime.llm_aborted() or runtime.is_send_blocked():
            logger.warning(f"停止中：取消对 {user_id} 的辅助模型调用")
            return None
        try:
            logger.debug(f"发送给辅助模型 API 的消息 (ID: {user_id}): {messages_to_send}")

            response = assistant_client.chat.completions.create(
                model=ASSISTANT_MODEL,
                messages=messages_to_send,
                temperature=ASSISTANT_TEMPERATURE,
                max_tokens=ASSISTANT_MAX_TOKEN,
                stream=False
            )

            if response.choices:
                # 检查辅助模型API是否返回了空的消息内容
                message_content = response.choices[0].message.content
                if message_content is None:
                    logger.error(f"辅助模型API返回了空的信息，可能是因为触发了安全检查机制，请修改Prompt并清空上下文再试 (ID: {user_id})")
                    logger.error(f"辅助模型错误请求消息体: {ASSISTANT_MODEL}")
                    logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
                    logger.error(f"完整响应对象: {response}")
                else:
                    content = message_content.strip()
                    if content and "[image]" not in content:
                        filtered_content = strip_before_thought_tags(content)
                        if filtered_content:
                            prompt_tokens, completion_tokens = _usage_tokens(response)
                            runtime.note_llm_call(
                                purpose,
                                "assistant",
                                (time.perf_counter() - started) * 1000,
                                True,
                                "",
                                prompt_tokens,
                                completion_tokens,
                            )
                            return filtered_content
            else:
                # 记录错误日志 - 无选择项
                logger.error(f"辅助模型API返回了空的选择项 (ID: {user_id})")
                logger.error(f"辅助模型错误请求消息体: {ASSISTANT_MODEL}")
                logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
                logger.error(f"完整响应对象: {response}")

            # 如果到这里说明内容为空或过滤后为空
            if response.choices and response.choices[0].message.content is not None:
                logger.error(f"辅助模型API返回了空的内容或内容被过滤 (ID: {user_id})")
            logger.error(f"辅助模型错误请求消息体: {ASSISTANT_MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))

        except Exception as e:
            logger.error("辅助模型错误请求消息体:")
            logger.error(f"{ASSISTANT_MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            error_info = str(e)
            logger.error(f"辅助模型自动重试：第 {attempt + 1} 次调用失败 (ID: {user_id}) 原因: {error_info}", exc_info=False)

            # 细化错误分类
            if "real name verification" in error_info:
                logger.error("\033[31m错误：API 服务商反馈请完成实名认证后再使用！\033[0m")
                break  # 终止循环，不再重试
            elif "rate limit" in error_info:
                logger.error("\033[31m错误：API 服务商反馈当前访问 API 服务频次达到上限，请稍后再试！\033[0m")
            elif "payment required" in error_info:
                logger.error("\033[31m错误：API 服务商反馈您正在使用付费模型，请先充值再使用或使用免费额度模型！\033[0m")
                break  # 终止循环，不再重试
            elif "user quota" in error_info or "is not enough" in error_info or "UnlimitedQuota" in error_info:
                logger.error("\033[31m错误：API 服务商反馈，你的余额不足，请先充值再使用! 如有余额，请检查令牌是否为无限额度。\033[0m")
                break  # 终止循环，不再重试
            elif "Api key is invalid" in error_info:
                logger.error("\033[31m错误：API 服务商反馈 API KEY 不可用，请检查配置选项！\033[0m")
            elif "service unavailable" in error_info:
                logger.error("\033[31m错误：API 服务商反馈服务器繁忙，请稍后再试！\033[0m")
            elif "sensitive words detected" in error_info or "sensitive" in error_info:
                logger.error("\033[31m错误：提示词中含有敏感词，无法生成回复，请联系API服务商！\033[0m")
                if ENABLE_SENSITIVE_CONTENT_CLEARING:
                    logger.warning(f"已开启敏感词自动清除上下文功能，开始清除用户 {user_id} 的聊天上下文和临时记忆")
                    clear_chat_context(user_id)
                    clear_memory_temp_files(user_id)  # 清除临时记忆文件
                break  # 终止循环，不再重试
            else:
                logger.error("\033[31m未知错误：" + error_info + "\033[0m")

        attempt += 1

    runtime.note_llm_call(
        purpose,
        "assistant",
        (time.perf_counter() - started) * 1000,
        False,
        "assistant_busy",
    )
    raise RuntimeError("抱歉，辅助模型现在有点忙，稍后再试吧。")


def recognize_image_with_moonshot(image_path, is_emoji=False):
    # 先暂停向API发送消息队列
    global can_send_messages
    can_send_messages = False
    started = time.perf_counter()
    purpose = "emoji_recognition" if is_emoji else "image_recognition"

    """使用AI识别图片内容并返回文本"""
    try:

        processed_image_path = image_path
        
        # 读取图片内容并编码
        with open(processed_image_path, 'rb') as img_file:
            image_content = base64.b64encode(img_file.read()).decode('utf-8')
            
        headers = {
            'Authorization': f'Bearer {MOONSHOT_API_KEY}',
            'Content-Type': 'application/json'
        }
        text_prompt = "请用中文描述这张图片的主要内容或主题。不要使用'这是'、'这张'等开头，直接描述。如果有文字，请包含在描述中。" if not is_emoji else "请用中文简洁地描述这个聊天窗口最后一张表情包所表达的情绪、含义或内容。如果表情包含文字，请一并描述。注意：1. 只描述表情包本身，不要添加其他内容 2. 不要出现'这是'、'这个'等词语"
        data = {
            "model": MOONSHOT_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_content}"}},
                        {"type": "text", "text": text_prompt}
                    ]
                }
            ],
            "temperature": MOONSHOT_TEMPERATURE
        }
        
        response = requests.post(f"{MOONSHOT_BASE_URL}/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        recognized_text = result['choices'][0]['message']['content']
        
        if is_emoji:
            # 如果recognized_text包含"最后一张表情包是"，只保留后面的文本
            if "最后一张表情包" in recognized_text:
                recognized_text = recognized_text.split("最后一张表情包", 1)[1].strip()
            recognized_text = "发送了表情包：" + recognized_text
        else:
            recognized_text = "发送了图片：" + recognized_text
            
        logger.info(f"AI图片识别结果: {recognized_text}")
        
        # 归档表情截图：从临时目录移动到 wechatauto_media\emoji 永久保存
        if is_emoji and os.path.exists(processed_image_path):
            try:
                archive_dir = os.path.join(
                    os.path.expanduser("~"), "Documents",
                    "wechatauto_media", "emoji")
                os.makedirs(archive_dir, exist_ok=True)
                dst = os.path.join(archive_dir, os.path.basename(processed_image_path))
                shutil.move(processed_image_path, dst)
                logger.debug(f"已归档表情截图: {dst}")
            except Exception as clean_err:
                logger.warning(f"归档表情截图失败: {clean_err}")
                try:
                    if os.path.exists(processed_image_path):
                        os.remove(processed_image_path)
                except Exception:
                    pass
                
        # 恢复向Deepseek发送消息队列
        can_send_messages = True
        prompt_tokens, completion_tokens = _usage_tokens(result)
        runtime.note_llm_call(
            purpose,
            "vision",
            (time.perf_counter() - started) * 1000,
            True,
            "",
            prompt_tokens,
            completion_tokens,
        )
        return recognized_text

    except Exception as e:
        logger.error(f"调用AI识别图片失败: {str(e)}", exc_info=True)
        # 恢复向Deepseek发送消息队列
        can_send_messages = True
        runtime.note_llm_call(
            purpose,
            "vision",
            (time.perf_counter() - started) * 1000,
            False,
            str(e),
        )
        return ""


# --- 检测是否需要联网搜索的函数 ---
def needs_online_search(message: str, user_id: str) -> Optional[str]:
    """
    使用主 AI 判断用户消息是否需要联网搜索，并返回需要搜索的内容。

    参数:
        message (str): 用户的消息。
        user_id (str): 用户标识符 (用于日志)。

    返回:
        Optional[str]: 如果需要联网搜索，返回需要搜索的内容；否则返回 None。
    """
    if not ENABLE_ONLINE_API:  # 如果全局禁用，直接返回 None
        return None

    # 构建用于检测的提示词
    detection_prompt = f"""
请判断以下用户消息是否明确需要查询当前、实时或非常具体的外部信息（例如：{SEARCH_DETECTION_PROMPT}）。
用户消息："{message}"

如果需要联网搜索，请回答 "需要联网"，并在下一行提供你认为需要搜索的内容，此内容包含修饰语，不缺失主干，意思明确，保证搜索后的内容准确。
如果不需要联网搜索（例如：常规聊天、角色扮演对话等），请只回答 "不需要联网"。
请不要添加任何其他解释。
"""
    try:
        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL and assistant_client:
            logger.info(f"向辅助模型发送联网检测请求，用户: {user_id}，消息: '{message[:50]}...'")
            response = get_assistant_response(detection_prompt, f"online_detection_{user_id}")
        else:
            logger.info(f"辅助模型未就绪，跳过联网检测以避免额外主模型调用。用户: {user_id}")
            return None

        # 清理并判断响应
        cleaned_response = (response or "").strip()
        if "</think>" in cleaned_response:
            cleaned_response = cleaned_response.split("</think>", 1)[1].strip()
        
        if ENABLE_ASSISTANT_MODEL:
            logger.info(f"辅助模型联网检测响应: '{cleaned_response}'")
        else:
            logger.info(f"主模型联网检测响应: '{cleaned_response}'")

        if "不需要联网" in cleaned_response:
            logger.info(f"用户 {user_id} 的消息不需要联网。")
            return None
        elif "需要联网" in cleaned_response:
            # 提取需要搜索的内容
            search_content = cleaned_response.split("\n", 1)[1].strip() if "\n" in cleaned_response else ""
            logger.info(f"检测到用户 {user_id} 的消息需要联网，搜索内容: '{search_content}'")
            return search_content
        else:
            logger.warning(f"无法解析联网检测响应，用户: {user_id}，响应: '{cleaned_response}'")
            return None

    except Exception as e:
        logger.error(f"联网检测失败，用户: {user_id}，错误: {e}", exc_info=True)
        return None  # 出错时默认不需要联网

# --- 调用在线模型的函数 ---


# --- 调用在线模型的函数 ---
def get_online_model_response(query: str, user_id: str) -> Optional[str]:
    """
    使用配置的在线 API 获取搜索结果。

    参数:
        query (str): 要发送给在线模型的查询（通常是用户消息）。
        user_id (str): 用户标识符 (用于日志)。

    返回:
        Optional[str]: 在线 API 的回复内容，如果失败则返回 None。
    """
    if not online_client: # 检查在线客户端是否已成功初始化
        logger.error(f"在线 API 客户端未初始化，无法为用户 {user_id} 执行在线搜索。")
        return None

    started = time.perf_counter()
    # 获取当前时间并格式化为字符串
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 结合固定的提示词、当前时间和用户查询
    online_query_prompt = f"请在互联网上查找相关信息，忽略过时信息，并给出简要的回答。\n{ONLINE_FIXED_PROMPT}\n当前时间：{current_time_str}\n\n{query}"

    try:
        logger.info(f"调用在线 API - 用户: {user_id}, 查询: '{query[:100]}...'")
        # 使用 online_client 调用在线模型
        response = online_client.chat.completions.create(
            model=ONLINE_MODEL,
            messages=[{"role": "user", "content": online_query_prompt}],
            temperature=ONLINE_API_TEMPERATURE,
            max_tokens=ONLINE_API_MAX_TOKEN,
            stream=False
        )

        if not response.choices:
            logger.error(f"在线 API 返回了空的选择项，用户: {user_id}")
            runtime.note_llm_call("online_search", "online", (time.perf_counter() - started) * 1000, False, "empty_choices")
            return None

        # 检查在线API是否返回了空的消息内容
        message_content = response.choices[0].message.content
        if message_content is None:
            logger.error(f"在线API返回了空的信息，可能是因为触发了安全检查机制，请修改Prompt并清空上下文再试 (用户: {user_id})")
            runtime.note_llm_call("online_search", "online", (time.perf_counter() - started) * 1000, False, "empty_content")
            return None

        reply = message_content.strip()
        # 清理回复，去除思考过程
        if "</think>" in reply:
            reply = reply.split("</think>", 1)[1].strip()
        logger.info(f"在线 API 响应 (用户 {user_id}): {reply}")
        prompt_tokens, completion_tokens = _usage_tokens(response)
        runtime.note_llm_call(
            "online_search",
            "online",
            (time.perf_counter() - started) * 1000,
            True,
            "",
            prompt_tokens,
            completion_tokens,
        )
        return reply

    except Exception as e:
        logger.error(f"调用在线 API 失败，用户: {user_id}: {e}", exc_info=True)
        runtime.note_llm_call("online_search", "online", (time.perf_counter() - started) * 1000, False, str(e))
        return "抱歉，在线搜索功能暂时出错了。"


def _extractor_log_purpose(purpose: str = "") -> str:
    """仅用于 telemetry / audit / 日志标签。不进入 request body。"""
    allowed = {
        "topic_extractor": "topic_extractor",
        "task_extractor": "task_extractor",
        "decision_extractor": "decision_extractor",
        "risk_extractor": "risk_extractor",
    }
    token = str(purpose or "").strip()
    return allowed.get(token, "topic_extractor")


def get_extractor_response(
    messages,
    temperature=0.2,
    max_tokens=1200,
    timeout=20,
    store_context=False,
    model="INHERIT",
    purpose="topic_extractor",
):
    """Extractor 独立调用。禁止 Chat Prompt、会话上下文和微信回复文案。

    purpose 只影响 note_llm_call / 日志标签，不得进入 HTTP request body。
    """
    import logging
    import threading
    import time as _time

    _ = store_context
    log = logging.getLogger(__name__)
    host_runtime = globals().get("runtime")
    if host_runtime is not None:
        try:
            if host_runtime.llm_aborted() or host_runtime.is_send_blocked():
                raise TimeoutError("EXTRACTOR_ABORTED")
        except TimeoutError:
            raise
        except Exception:
            pass

    openai_client, model_name = _resolver_extractor_client(model)
    if openai_client is None or not model_name:
        raise RuntimeError("EXTRACTOR_CLIENT_UNAVAILABLE")

    timeout_sec = float(timeout or 20)
    box = {}

    def _invoke():
        caller = openai_client
        if hasattr(openai_client, "with_options"):
            try:
                caller = openai_client.with_options(timeout=timeout_sec)
            except Exception:
                caller = openai_client
        box["response"] = caller.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=float(temperature if temperature is not None else 0.2),
            max_tokens=int(max_tokens or 800),
            stream=False,
        )

    worker = threading.Thread(target=lambda: _invoke_extractor(_invoke, box), name="TopicExtractorLLM", daemon=True)
    worker.start()
    worker.join(timeout_sec)
    if worker.is_alive():
        raise TimeoutError("EXTRACTOR_TIMEOUT")
    if box.get("error"):
        err = box["error"]
        text = str(err).lower()
        if "timeout" in text or err.__class__.__name__.lower().find("timeout") >= 0:
            raise TimeoutError("EXTRACTOR_TIMEOUT")
        raise RuntimeError(str(err)[:300])
    response = box.get("response")
    if response is None:
        raise RuntimeError("EXTRACTOR_EMPTY")
    content = _extractor_choice_text(response)
    if not content:
        # reasoning 模型偶发只填 reasoning_content，或首包为空；独立入口内重试一次。
        try:
            _invoke()
            response = box.get("response")
            content = _extractor_choice_text(response)
        except Exception:
            content = ""
    if not content:
        raise RuntimeError("EXTRACTOR_EMPTY")
    duration_ms = (_time.perf_counter() - box.get("started", _time.perf_counter())) * 1000
    purpose_label = _extractor_log_purpose(purpose)
    if host_runtime is not None and hasattr(host_runtime, "note_llm_call"):
        try:
            prompt_tokens, completion_tokens = _usage_tokens(response)
            host_runtime.note_llm_call(
                purpose_label,
                "extractor",
                duration_ms,
                True,
                "",
                prompt_tokens,
                completion_tokens,
            )
        except Exception:
            pass
    log.info("%s LLM ok model=%s", purpose_label, model_name)
    return content


def _invoke_extractor(fn, box):
    import time as _time
    box["started"] = _time.perf_counter()
    try:
        fn()
    except Exception as exc:
        box["error"] = exc


def _extractor_choice_text(response) -> str:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        message = choices[0].message
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        text = _finish_extractor_text(content)
        if _looks_like_extractor_json(text):
            return text
        reason = getattr(message, "reasoning_content", None)
        if reason is None and isinstance(message, dict):
            reason = message.get("reasoning_content")
        reason_text = _finish_extractor_text(reason)
        if _looks_like_extractor_json(reason_text):
            return reason_text
        return text
    except Exception:
        return ""


def _finish_extractor_text(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    filtered = strip_before_thought_tags(text)
    if filtered:
        text = str(filtered).strip()
    return text


def _looks_like_extractor_json(text: str) -> bool:
    value = str(text or "")
    return "{" in value and '"decision"' in value


def _resolver_extractor_client(model: str):
    host_client = globals().get("client")
    host_model = globals().get("MODEL")
    model_name = model if model and str(model) != "INHERIT" else host_model
    if host_client is not None and model_name:
        return host_client, str(model_name)
    try:
        from app_config import is_configured_secret, load_config
        from openai import OpenAI
        cfg = load_config()
        model_name = model if model and str(model) != "INHERIT" else cfg.get("MODEL")
        api_key = cfg.get("DEEPSEEK_API_KEY")
        if not is_configured_secret(api_key):
            return None, None
        client = OpenAI(api_key=api_key, base_url=cfg.get("DEEPSEEK_BASE_URL") or None)
        return client, str(model_name or "")
    except Exception:
        return None, None


def call_narrow_completion(messages, timeout=8, max_tokens=128, temperature=0, purpose="query_intent"):
    """独立窄补全。调用方传入完整 messages。

    不读 Chat Prompt，不读会话记录，不写会话记录，不清理记忆。
    不修改全局 Chat 客户端的 timeout。单次等待由本次 with_options 和线程 join 限制。
    """
    import logging
    import threading
    import time as _time

    log = logging.getLogger(__name__)
    host_runtime = globals().get("runtime")
    if host_runtime is not None:
        try:
            if host_runtime.llm_aborted() or host_runtime.is_send_blocked():
                raise TimeoutError("QUERY_INTENT_ABORTED")
        except TimeoutError:
            raise
        except Exception:
            pass

    openai_client = globals().get("client")
    model_name = globals().get("MODEL")
    if openai_client is None or not model_name:
        openai_client, model_name = _resolver_extractor_client("INHERIT")
    if openai_client is None or not model_name:
        raise ConnectionError("QUERY_INTENT_CLIENT_UNAVAILABLE")

    checker = globals().get("_is_base_url_untrusted")
    base_url = globals().get("DEEPSEEK_BASE_URL")
    if callable(checker) and base_url and checker(base_url):
        from llm_errors import LlmApiError, UNTRUSTED_PROVIDER, USER_MESSAGES
        raise LlmApiError(
            UNTRUSTED_PROVIDER,
            USER_MESSAGES[UNTRUSTED_PROVIDER],
            "untrusted provider",
        )

    timeout_sec = 8.0 if timeout is None else float(timeout)
    if timeout_sec <= 0:
        timeout_sec = 8.0
    token_limit = int(max_tokens or 128)
    temp = 0.0 if temperature is None else float(temperature)
    payload = list(messages or [])
    box = {}
    started = _time.perf_counter()

    def _invoke():
        caller = openai_client
        if hasattr(openai_client, "with_options"):
            try:
                caller = openai_client.with_options(timeout=timeout_sec, max_retries=0)
            except Exception:
                caller = openai_client
        try:
            box["response"] = caller.chat.completions.create(
                model=model_name,
                messages=payload,
                temperature=temp,
                max_tokens=token_limit,
                stream=False,
            )
        except Exception as exc:
            box["error"] = exc

    worker = threading.Thread(target=_invoke, name="QueryIntentLLM", daemon=True)
    worker.start()
    worker.join(timeout_sec)
    if worker.is_alive():
        raise TimeoutError("QUERY_INTENT_TIMEOUT")
    if box.get("error") is not None:
        err = box["error"]
        text = str(err).lower()
        if "timeout" in text or "timed out" in text:
            raise TimeoutError("QUERY_INTENT_TIMEOUT")
        raise err

    response = box.get("response")
    content = ""
    if response is not None:
        try:
            choices = getattr(response, "choices", None) or []
            if choices:
                message = choices[0].message
                raw = getattr(message, "content", None)
                if raw is None and isinstance(message, dict):
                    raw = message.get("content")
                content = str(raw or "").strip()
        except Exception:
            content = ""
    if content:
        filtered = strip_before_thought_tags(content)
        if filtered:
            content = str(filtered).strip()
    if host_runtime is not None and hasattr(host_runtime, "note_llm_call"):
        try:
            prompt_tokens, completion_tokens = _usage_tokens(response) if response is not None else (0, 0)
            host_runtime.note_llm_call(
                str(purpose or "query_intent"),
                "main",
                (_time.perf_counter() - started) * 1000,
                bool(content),
                "" if content else "empty",
                prompt_tokens,
                completion_tokens,
            )
        except Exception:
            pass
    if content:
        log.info("query_intent narrow completion ok model=%s", model_name)
    return content

