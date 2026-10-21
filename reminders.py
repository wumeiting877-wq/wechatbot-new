# -*- coding: utf-8 -*-
"""提醒解析、持久化与到期检查。函数在 bot 宿主安装后使用其全局命名空间。"""

from __future__ import annotations

import json
import re
from typing import Optional

from module_install import install_exports

EXPORTS = (
    "try_parse_and_set_reminder",
    "extract_last_json_or_null",
    "format_delay_approx",
    "send_confirmation_reply",
    "trigger_reminder",
    "load_recurring_reminders",
    "save_recurring_reminders",
    "recurring_reminder_checker",
)


def install_into(module) -> None:
    install_exports(globals(), EXPORTS, module)


def try_parse_and_set_reminder(message_content, user_id):
    """
    尝试解析消息内容，区分短期一次性、长期一次性、重复提醒。
    使用 AI 进行分类和信息提取，然后设置短期定时器或保存到文件。
    如果成功设置了任一类型的提醒，返回 True，否则返回 False。
    """
    global next_timer_id # 引用全局变量，用于生成短期一次性提醒的ID
    logger.debug(f"尝试为用户 {user_id} 解析提醒请求 (需要识别类型和时长): '{message_content}'")

    try:
        # --- 1. 获取当前时间，准备给 AI 的上下文信息 ---
        now = dt.datetime.now()
        # AI 需要知道当前完整日期时间来计算目标时间
        current_datetime_str_for_ai = now.strftime("%Y-%m-%d %A %H:%M:%S")
        logger.debug(f"当前时间: {current_datetime_str_for_ai} (用于AI分析)")

        # --- 2. 构建新的 AI 提示，要求 AI 分类并提取信息 ---
        # --- 更新: 增加短期/长期一次性提醒的区分 ---
        parsing_prompt = f"""
请分析用户的提醒或定时请求。
当前时间是: {current_datetime_str_for_ai}.
用户的请求是: "{message_content}"

请判断这个请求属于以下哪种类型，并计算相关时间：
A) **重复性每日提醒**：例如 "每天早上8点叫我起床", "提醒我每天晚上10点睡觉"。
B) **一次性提醒 (延迟 > 10分钟 / 600秒)**：例如 "1小时后提醒我", "今天下午3点开会", "明天早上叫我"。
C) **一次性提醒 (延迟 <= 10分钟 / 600秒)**：例如 "5分钟后提醒我", "提醒我600秒后喝水"。
D) **非提醒请求**：例如 "今天天气怎么样?", "取消提醒"。

根据判断结果，请严格按照以下格式输出：
- 如果是 A (重复每日提醒): 返回 JSON 对象 `{{"type": "recurring", "time_str": "HH:MM", "message": "提醒的具体内容"}}`。 `time_str` 必须是 24 小时制的 HH:MM 格式。
- 如果是 B (长期一次性提醒): 返回 JSON 对象 `{{"type": "one-off-long", "target_datetime_str": "YYYY-MM-DD HH:MM", "message": "提醒的具体内容"}}`。 `target_datetime_str` 必须是计算出的未来目标时间的 YYYY-MM-DD HH:MM 格式。
- 如果是 C (短期一次性提醒): 返回 JSON 对象 `{{"type": "one-off-short", "delay_seconds": number, "message": "提醒的具体内容"}}`。 `delay_seconds` 必须是从现在开始计算的、小于等于 600 的正整数总秒数。
- 如果是 D (非提醒): 请直接返回字面单词 `null`。

请看以下例子 (假设当前时间是 2024-05-29 星期三 10:00:00):
1. "每天早上8点叫我起床" -> `{{"type": "recurring", "time_str": "08:00", "message": "叫我起床"}}`
2. "提醒我30分钟后喝水" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-29 10:30", "message": "喝水"}}` (超过10分钟)
3. "下午2点提醒我开会" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-29 14:00", "message": "开会"}}`
4. "明天早上7点叫我起床" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-30 07:00", "message": "叫我起床"}}`
5. "提醒我5分钟后站起来活动" -> `{{"type": "one-off-short", "delay_seconds": 300, "message": "站起来活动"}}` (小于等于10分钟)
6. "10分钟后叫我" -> `{{"type": "one-off-short", "delay_seconds": 600, "message": "叫我"}}` (等于10分钟)
7. "今天怎么样?" -> `null`

请务必严格遵守输出格式，只返回指定的 JSON 对象或 `null`，不要添加任何解释性文字。
"""
        # --- 3. 调用 AI 进行解析和分类 ---
        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL and assistant_client:
            logger.info(f"向辅助模型发送提醒解析请求（区分时长），用户: {user_id}，内容: '{message_content}'")
            ai_raw_response = get_assistant_response(parsing_prompt, "reminder_parser_classifier_v2_" + user_id)
            logger.debug(f"辅助模型提醒解析原始响应 (分类器 v2): {ai_raw_response}")
        else:
            logger.info(f"向主模型发送提醒解析请求（区分时长），用户: {user_id}，内容: '{message_content}'")
            ai_raw_response = get_deepseek_response(parsing_prompt, user_id="reminder_parser_classifier_v2_" + user_id, store_context=False)
            logger.debug(f"主模型提醒解析原始响应 (分类器 v2): {ai_raw_response}")

        # 使用新的清理函数处理AI的原始响应
        cleaned_ai_output_str = extract_last_json_or_null(ai_raw_response)
        logger.debug(f"AI响应清理并提取后内容: '{cleaned_ai_output_str}'")
        response = cleaned_ai_output_str

        # --- 4. 解析 AI 的响应 ---
        # 修改判断条件，使用清理后的结果
        if cleaned_ai_output_str is None or cleaned_ai_output_str == "null": # "null" 是AI明确表示非提醒的方式
            logger.info(f"AI 未在用户 '{user_id}' 的消息中检测到有效的提醒请求 (清理后结果为 None 或 'null')。原始AI响应: '{ai_raw_response}'")
            return False
        
        try:
            response_cleaned = re.sub(r"```json\n?|\n?```", "", response).strip()
            reminder_data = json.loads(response_cleaned)
            logger.debug(f"解析后的JSON数据 (分类器 v2): {reminder_data}")

            reminder_type = reminder_data.get("type")
            reminder_msg = str(reminder_data.get("message", "")).strip()

            # --- 5. 验证共享数据（提醒内容不能为空）---
            if not reminder_msg:
                logger.warning(f"从AI解析得到的提醒消息为空。用户: {user_id}, 数据: {reminder_data}")
                error_prompt = f"用户尝试设置提醒，但似乎没有说明要提醒的具体内容（用户的原始请求可能是 '{message_content}'）。请用你的语气向用户解释需要提供提醒内容，并鼓励他们再说一次。"
                fallback = "嗯... 光设置时间还不行哦，得告诉我你要我提醒你做什么事呀？"
                send_error_reply(user_id, error_prompt, fallback, "提醒内容为空")
                return False

            # --- 6. 根据 AI 判断的类型分别处理 ---

            # --- 6a. 短期一次性提醒 (<= 10分钟) ---
            if reminder_type == "one-off-short":
                try:
                    delay_seconds = int(reminder_data['delay_seconds'])
                    if not (0 < delay_seconds <= 600): # 验证延迟在 (0, 600] 秒之间
                         logger.warning(f"AI 返回的 'one-off-short' 延迟时间无效: {delay_seconds} 秒 (应 > 0 且 <= 600)。用户: {user_id}, 数据: {reminder_data}")
                         error_prompt = f"用户想设置一个短期提醒（原始请求 '{message_content}'），但我计算出的时间 ({delay_seconds}秒) 不在10分钟内或已过去。请用你的语气告诉用户这个时间有点问题，建议他们检查一下或换个说法。"
                         fallback = "哎呀，这个短期提醒的时间好像有点不对劲（要么超过10分钟，要么已经过去了），能麻烦你再说一次吗？"
                         send_error_reply(user_id, error_prompt, fallback, "短期延迟时间无效")
                         return False
                except (KeyError, ValueError, TypeError) as val_e:
                     logger.error(f"解析AI返回的 'one-off-short' 提醒数据失败。用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                     error_prompt = f"用户想设置短期提醒（原始请求 '{message_content}'），但我没理解好时间({type(val_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们换种方式说，比如'5分钟后提醒我...'"
                     fallback = "抱歉呀，我好像没太明白你的时间意思，设置短期提醒失败了。能麻烦你换种方式再说一遍吗？比如 '5分钟后提醒我...'"
                     send_error_reply(user_id, error_prompt, fallback, f"One-off-short数据解析失败 ({type(val_e).__name__})")
                     return False

                # 设置 threading.Timer 定时器
                target_dt = now + dt.timedelta(seconds=delay_seconds)
                confirmation_time_str = target_dt.strftime('%Y-%m-%d %H:%M:%S')
                delay_str_approx = format_delay_approx(delay_seconds, target_dt)

                logger.info(f"准备为用户 {user_id} 设置【短期一次性】提醒 (<=10min)，计划触发时间: {confirmation_time_str} (延迟 {delay_seconds:.2f} 秒)，内容: '{reminder_msg}'")

                with timer_lock:
                    timer_id = next_timer_id
                    next_timer_id += 1
                    timer_key = (user_id, timer_id)
                    timer = Timer(float(delay_seconds), trigger_reminder, args=[user_id, timer_id, reminder_msg])
                    active_timers[timer_key] = timer
                    timer.start()
                    logger.info(f"【短期一次性】提醒定时器 (ID: {timer_id}) 已为用户 {user_id} 成功启动。")

                log_original_message_to_memory(user_id, message_content) # 记录原始请求

                confirmation_prompt = f"""用户刚才的请求是："{message_content}"。
根据这个请求，你已经成功将一个【短期一次性】提醒（10分钟内）安排在 {confirmation_time_str} (也就是 {delay_str_approx}) 触发。
提醒的核心内容是：'{reminder_msg}'。
请你用自然、友好的语气回复用户，告诉他这个【短期】提醒已经设置好了，确认时间和提醒内容。"""
                send_confirmation_reply(user_id, confirmation_prompt, f"[短期一次性提醒已设置: {reminder_msg}]", f"收到！【短期提醒】设置好啦，我会在 {delay_str_approx} ({target_dt.strftime('%H:%M')}) 提醒你：{reminder_msg}")
                return True

            # --- 6b. 长期一次性提醒 (> 10分钟) ---
            elif reminder_type == "one-off-long":
                try:
                    target_datetime_str = reminder_data['target_datetime_str']
                    # 在本地再次验证时间格式是否为 YYYY-MM-DD HH:MM
                    target_dt = datetime.strptime(target_datetime_str, '%Y-%m-%d %H:%M')
                    # 验证时间是否在未来
                    if target_dt <= now:
                        logger.warning(f"AI 返回的 'one-off-long' 目标时间无效: {target_datetime_str} (已过去或就是现在)。用户: {user_id}, 数据: {reminder_data}")
                        error_prompt = f"用户想设置一个提醒（原始请求 '{message_content}'），但我计算出的目标时间 ({target_datetime_str}) 好像是过去或就是现在了。请用你的语气告诉用户这个时间点无法设置，建议他们指定一个未来的时间。"
                        fallback = "哎呀，这个时间点 ({target_dt.strftime('%m月%d日 %H:%M')}) 好像已经过去了或就是现在啦，没办法设置过去的提醒哦。要不试试说一个未来的时间？"
                        send_error_reply(user_id, error_prompt, fallback, "长期目标时间无效")
                        return False
                except (KeyError, ValueError, TypeError) as val_e:
                    logger.error(f"解析AI返回的 'one-off-long' 提醒数据失败。用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                    error_prompt = f"用户想设置一个较远时间的提醒（原始请求 '{message_content}'），但我没理解好目标时间 ({type(val_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们用明确的日期和时间再说，比如'明天下午3点'或'2024-06-15 10:00'。"
                    fallback = "抱歉呀，我好像没太明白你说的那个未来的时间点，设置提醒失败了。能麻烦你说得更清楚一点吗？比如 '明天下午3点' 或者 '6月15号上午10点' 这样。"
                    send_error_reply(user_id, error_prompt, fallback, f"One-off-long数据解析失败 ({type(val_e).__name__})")
                    return False

                logger.info(f"准备为用户 {user_id} 添加【长期一次性】提醒 (>10min)，目标时间: {target_datetime_str}，内容: '{reminder_msg}'")

                # 创建要存储的提醒信息字典 (包含类型)
                new_reminder = {
                    "reminder_type": "one-off", # 在存储时统一用 'one-off'
                    "user_id": user_id,
                    "target_datetime_str": target_datetime_str, # 存储目标时间
                    "content": reminder_msg
                }

                # 添加到内存列表并保存到文件
                with recurring_reminder_lock:
                    recurring_reminders.append(new_reminder)
                    save_recurring_reminders() # 保存更新后的列表

                logger.info(f"【长期一次性】提醒已添加并保存到文件。用户: {user_id}, 时间: {target_datetime_str}, 内容: '{reminder_msg}'")

                log_original_message_to_memory(user_id, message_content)

                # 发送确认消息
                confirmation_prompt = f"""用户刚才的请求是："{message_content}"。
根据这个请求，你已经成功为他设置了一个【一次性】提醒。
这个提醒将在【指定时间】 {target_datetime_str} 触发。
提醒的核心内容是：'{reminder_msg}'。
请你用自然、友好的语气回复用户，告诉他这个【一次性】提醒已经设置好了，确认好具体的日期时间和提醒内容。"""
                # 使用格式化后的时间发送给用户
                friendly_time = target_dt.strftime('%Y年%m月%d日 %H:%M')
                send_confirmation_reply(user_id, confirmation_prompt, f"[长期一次性提醒已设置: {reminder_msg}]", f"好嘞！【一次性提醒】设置好啦，我会在 {friendly_time} 提醒你：{reminder_msg}")
                return True

            # --- 6c. 重复性每日提醒 ---
            elif reminder_type == "recurring":
                try:
                    time_str = reminder_data['time_str']
                    datetime.strptime(time_str, '%H:%M') # 验证 HH:MM 格式
                except (KeyError, ValueError, TypeError) as val_e:
                    logger.error(f"解析AI返回的 'recurring' 提醒数据失败。用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                    error_prompt = f"用户想设置每日提醒（原始请求 '{message_content}'），但我没理解好时间 ({type(val_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们用明确的'每天几点几分'格式再说，比如'每天早上8点'或'每天22:30'。"
                    fallback = "抱歉呀，我好像没太明白你说的每日提醒时间，设置失败了。能麻烦你说清楚是'每天几点几分'吗？比如 '每天早上8点' 或者 '每天22:30' 这样。"
                    send_error_reply(user_id, error_prompt, fallback, f"Recurring数据解析失败 ({type(val_e).__name__})")
                    return False

                logger.info(f"准备为用户 {user_id} 添加【每日重复】提醒，时间: {time_str}，内容: '{reminder_msg}'")

                # 创建要存储的提醒信息字典 (包含类型)
                new_reminder = {
                    "reminder_type": "recurring", # 明确类型
                    "user_id": user_id,
                    "time_str": time_str, # 存储 HH:MM
                    "content": reminder_msg
                }

                # 添加到内存列表并保存到文件
                with recurring_reminder_lock:
                    # 检查是否已存在完全相同的重复提醒
                    exists = any(
                        r.get('reminder_type') == 'recurring' and
                        r.get('user_id') == user_id and
                        r.get('time_str') == time_str and
                        r.get('content') == reminder_msg
                        for r in recurring_reminders
                    )
                    if not exists:
                        recurring_reminders.append(new_reminder)
                        save_recurring_reminders()
                        logger.info(f"【每日重复】提醒已添加并保存。用户: {user_id}, 时间: {time_str}, 内容: '{reminder_msg}'")
                    else:
                        logger.info(f"相同的【每日重复】提醒已存在，未重复添加。用户: {user_id}, 时间: {time_str}")
                        # 可以选择告知用户提醒已存在
                        # send_reply(user_id, user_id, user_id, "[重复提醒已存在]", f"嗯嗯，这个 '{reminder_msg}' 的每日 {time_str} 提醒我已经记下啦，不用重复设置哦。")
                        # return True # 即使未添加，也认为设置意图已满足

                log_original_message_to_memory(user_id, message_content)

                # 向用户发送确认消息
                confirmation_prompt = f"""用户刚才的请求是："{message_content}"。
根据这个请求，你已经成功为他设置了一个【每日重复】提醒。
这个提醒将在【每天】的 {time_str} 触发。
提醒的核心内容是：'{reminder_msg}'。
请你用自然、友好的语气回复用户，告诉他【每日】提醒已经设置好了，确认时间和提醒内容。强调这是每天都会提醒的。"""
                send_confirmation_reply(user_id, confirmation_prompt, f"[每日提醒已设置: {reminder_msg}]", f"好嘞！【每日提醒】设置好啦，以后我【每天】 {time_str} 都会提醒你：{reminder_msg}")
                return True

            # --- 6d. 未知类型 ---
            else:
                 logger.error(f"AI 返回了未知的提醒类型: '{reminder_type}'。用户: {user_id}, 数据: {reminder_data}")
                 error_prompt = f"用户想设置提醒（原始请求 '{message_content}'），但我有点糊涂了，没搞清楚时间或者类型。请用你的语气抱歉地告诉用户，请他们说得更清楚一点，比如是几分钟后、明天几点、还是每天提醒。"
                 fallback = "哎呀，我有点没搞懂你的提醒要求，是几分钟后提醒，还是指定某个时间点，或者是每天都提醒呀？麻烦说清楚点我才能帮你设置哦。"
                 send_error_reply(user_id, error_prompt, fallback, f"未知提醒类型 '{reminder_type}'")
                 return False

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as json_e:
            # 处理 JSON 解析本身或后续访问键值对的错误
            response_cleaned_str = response_cleaned if 'response_cleaned' in locals() else 'N/A'
            logger.error(f"解析AI返回的提醒JSON失败 (分类器 v2)。用户: {user_id}, 原始响应: '{response}', 清理后: '{response_cleaned_str}', 错误: {json_e}")
            error_prompt = f"用户想设置提醒（原始请求可能是 '{message_content}'），但我好像没完全理解时间或者内容，解析的时候出错了 ({type(json_e).__name__})。请用你的语气抱歉地告诉用户没听懂，并请他们换种方式说，比如'30分钟后提醒我...'或'每天下午3点叫我...'。"
            fallback = "抱歉呀，我好像没太明白你的意思，设置提醒失败了。能麻烦你换种方式再说一遍吗？比如 '30分钟后提醒我...' 或者 '每天下午3点叫我...' 这种。"
            send_error_reply(user_id, error_prompt, fallback, f"JSON解析失败 ({type(json_e).__name__})")
            return False

    except Exception as e:
        # 捕获此函数中其他所有未预料的错误
        logger.error(f"处理用户 {user_id} 的提醒请求 '{message_content}' 时发生未预料的错误 (分类器 v2): {str(e)}", exc_info=True)
        error_prompt = f"在处理用户设置提醒的请求（可能是 '{message_content}'）时，发生了一个我没预料到的内部错误（{type(e).__name__}）。请用你的语气向用户表达歉意，说明暂时无法完成设置，并建议他们稍后再试。"
        fallback = "哎呀，好像内部出了点小问题，暂时没法帮你设置提醒了，非常抱歉！要不稍等一下再试试看？"
        send_error_reply(user_id, error_prompt, fallback, f"通用处理错误 ({type(e).__name__})")
        return False


def extract_last_json_or_null(ai_response_text: str) -> Optional[str]:
    """
    从AI的原始响应文本中清理并提取最后一个有效的JSON对象字符串或字面量 "null"。

    Args:
        ai_response_text: AI返回的原始文本。

    Returns:
        如果找到有效的JSON对象，则返回其字符串形式。
        如果AI明确返回 "null" (清理后)，则返回字符串 "null"。
        如果没有找到有效的JSON或 "null"，则返回 None。
    """
    if ai_response_text is None:
        return None

    # 步骤 1: 移除常见的Markdown代码块标记，并去除首尾空格
    # 这个正则表达式会移除 ```json\n, ```json, \n```, ```
    processed_text = re.sub(r"```json\n?|\n?```", "", ai_response_text).strip()

    # 步骤 2: 检查清理后的文本是否完全是 "null" (不区分大小写)
    # 这是AI指示非提醒请求的明确信号
    if processed_text.lower() == 'null':
        return "null" # 返回字面量字符串 "null"

    # 步骤 3: 查找所有看起来像JSON对象的子字符串
    # re.DOTALL 使得 '.' 可以匹配换行符
    # 这个正则表达式会找到所有以 '{' 开头并以 '}' 结尾的非重叠子串
    json_candidates = re.findall(r'\{.*?\}', processed_text, re.DOTALL)

    if not json_candidates:
        # 没有找到任何类似JSON的结构，并且它也不是 "null"
        return None

    # 步骤 4: 从后往前尝试解析每个候选JSON字符串
    for candidate_str in reversed(json_candidates):
        try:
            # 尝试解析以验证它是否是有效的JSON
            json.loads(candidate_str)
            # 如果成功解析，说明这是最后一个有效的JSON对象字符串
            return candidate_str
        except json.JSONDecodeError:
            # 解析失败，继续尝试前一个候选者
            continue

    # 如果所有候选者都解析失败
    return None


def format_delay_approx(delay_seconds, target_dt):
    """将延迟秒数格式化为用户友好的大致时间描述。"""
    if delay_seconds < 60:
        # 少于1分钟，显示秒
        return f"大约 {int(delay_seconds)} 秒后"
    elif delay_seconds < 3600:
        # 少于1小时，显示分钟
        return f"大约 {int(delay_seconds / 60)} 分钟后"
    elif delay_seconds < 86400:
        # 少于1天，显示小时和分钟
        hours = int(delay_seconds / 3600)
        minutes = int((delay_seconds % 3600) / 60)
        # 如果分钟数为0，则只显示小时
        return f"大约 {hours} 小时" + (f" {minutes} 分钟后" if minutes > 0 else "后")
    else:
        # 超过1天，显示天数和目标日期时间
        days = int(delay_seconds / 86400)
        # 使用中文日期时间格式
        return f"大约 {days} 天后 ({target_dt.strftime('%Y年%m月%d日 %H:%M')}左右)"


def send_confirmation_reply(user_id, confirmation_prompt, log_context, fallback_message):
    """使用 AI 生成并发送提醒设置成功的确认消息，包含备用消息逻辑。"""
    logger.debug(f"准备发送给 AI 用于生成确认消息的提示词（部分）: {confirmation_prompt[:250]}...")
    try:
        # 调用 AI 生成确认回复，存储上下文
        confirmation_msg = get_deepseek_response(confirmation_prompt, user_id=user_id, store_context=True)
        logger.info(f"已为用户 {user_id} 生成提醒确认消息: {confirmation_msg[:100]}...")
        # 使用 send_reply 发送 AI 生成的确认消息
        send_reply(user_id, user_id, user_id, log_context, confirmation_msg)
        logger.info(f"已通过 send_reply 向用户 {user_id} 发送提醒确认消息。")
    except Exception as api_err:
        # 如果 AI 调用失败
        logger.error(f"调用API为用户 {user_id} 生成提醒确认消息失败: {api_err}. 将使用备用消息。")
        try:
             # 尝试使用 send_reply 发送预设的备用确认消息
             send_reply(user_id, user_id, user_id, f"{log_context} [备用确认]", fallback_message, is_system_message=True)
        except Exception as send_fallback_err:
             # 如果连发送备用消息都失败了，记录严重错误
             logger.critical(f"发送备用确认消息也失败 ({log_context}): {send_fallback_err}")

    
def trigger_reminder(user_id, timer_id, reminder_message):
    """当短期提醒到期时由 threading.Timer 调用的函数。"""
    global is_sending_message

    timer_key = (user_id, timer_id)
    logger.info(f"触发【短期】提醒 (ID: {timer_id})，用户 {user_id}，内容: {reminder_message}")

    # 从活动计时器列表中移除 (短期提醒)
    with timer_lock:
        if timer_key in active_timers:
            del active_timers[timer_key]
        else:
             logger.warning(f"触发时未在 active_timers 中找到短期计时器键 {timer_key}。")

    if is_quiet_time() and not ALLOW_REMINDERS_IN_QUIET_TIME:
        logger.info(f"当前为安静时间：抑制【短期】提醒 (ID: {timer_id})，用户 {user_id}。")
        return

    try:
        # 创建提醒前缀，让AI知道这是一个提醒触发
        reminder_prefix = f"提醒触发：{reminder_message}"
        
        # 将提醒消息添加到用户的消息队列，而不是直接调用API
        current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
        formatted_message = f"[{current_time_str}] {reminder_prefix}"
        
        with queue_lock:
            if user_id not in user_queues:
                user_queues[user_id] = {
                    'messages': [formatted_message],
                    'sender_name': user_id,
                    'username': user_id,
                    'last_message_time': time.time()
                }
            else:
                user_queues[user_id]['messages'].append(formatted_message)
                user_queues[user_id]['last_message_time'] = time.time()
        
        logger.info(f"已将提醒消息 '{reminder_message}' 添加到用户 {user_id} 的消息队列，用以执行联网检查流程")

        # 可选：如果仍需语音通话功能，保留这部分
        if get_dynamic_config('USE_VOICE_CALL_FOR_REMINDERS', USE_VOICE_CALL_FOR_REMINDERS):
            try:
                wx.VoiceCall(user_id)
                logger.info(f"通过语音通话提醒用户 {user_id} (短期提醒)。")
            except Exception as voice_err:
                logger.error(f"语音通话提醒失败 (短期提醒)，用户 {user_id}: {voice_err}")

    except Exception as e:
        logger.error(f"处理【短期】提醒失败 (ID: {timer_id})，用户 {user_id}: {str(e)}", exc_info=True)
        # 即使出错，也不再使用原来的直接发送备用消息方法
        # 而是尽可能添加到队列
        try:
            fallback_msg = f"[{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')}] 提醒时间到：{reminder_message}"
            with queue_lock:
                if user_id in user_queues:
                    user_queues[user_id]['messages'].append(fallback_msg)
                    user_queues[user_id]['last_message_time'] = time.time()
                else:
                    user_queues[user_id] = {
                        'messages': [fallback_msg],
                        'sender_name': user_id,
                        'username': user_id,
                        'last_message_time': time.time()
                    }
            logger.info(f"已将备用提醒消息添加到用户 {user_id} 的消息队列")
        except Exception as fallback_e:
            logger.error(f"添加提醒备用消息到队列失败，用户 {user_id}: {fallback_e}")


def load_recurring_reminders():
    """从 JSON 文件加载重复和长期一次性提醒到内存中。"""
    global recurring_reminders
    reminders_loaded = []
    try:
        if os.path.exists(RECURRING_REMINDERS_FILE):
            with open(RECURRING_REMINDERS_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    valid_reminders_count = 0
                    now = datetime.now() # 获取当前时间用于检查一次性提醒是否已过期
                    for item in loaded_data:
                        # 基本结构验证
                        if not (isinstance(item, dict) and
                                'reminder_type' in item and
                                'user_id' in item and
                                'content' in item):
                            logger.warning(f"跳过无效格式的提醒项: {item}")
                            continue

                        user_id = item.get('user_id')
                        reminder_type = item.get('reminder_type')
                        content = item.get('content')

                        # 用户有效性检查
                        if user_id not in user_names:
                             logger.warning(f"跳过未在监听列表中的用户提醒: {user_id}")
                             continue

                        # 类型特定验证
                        is_valid = False
                        if reminder_type == 'recurring':
                            time_str = item.get('time_str')
                            if time_str:
                                try:
                                    datetime.strptime(time_str, '%H:%M')
                                    is_valid = True
                                except ValueError:
                                    logger.warning(f"跳过无效时间格式的重复提醒: {item}")
                            else:
                                logger.warning(f"跳过缺少 time_str 的重复提醒: {item}")
                        elif reminder_type == 'one-off':
                            target_datetime_str = item.get('target_datetime_str')
                            if target_datetime_str:
                                try:
                                    target_dt = datetime.strptime(target_datetime_str, '%Y-%m-%d %H:%M')
                                    # 只加载未过期的一次性提醒
                                    if target_dt > now:
                                        is_valid = True
                                    else:
                                        logger.info(f"跳过已过期的一次性提醒: {item}")
                                except ValueError:
                                    logger.warning(f"跳过无效日期时间格式的一次性提醒: {item}")
                            else:
                                logger.warning(f"跳过缺少 target_datetime_str 的一次性提醒: {item}")
                        else:
                            logger.warning(f"跳过未知 reminder_type 的提醒: {item}")

                        if is_valid:
                            reminders_loaded.append(item)
                            valid_reminders_count += 1

                    # 使用锁安全地更新全局列表
                    with recurring_reminder_lock:
                        recurring_reminders = reminders_loaded
                    logger.info(f"成功从 {RECURRING_REMINDERS_FILE} 加载 {valid_reminders_count} 条有效提醒。")
                else:
                    logger.error(f"{RECURRING_REMINDERS_FILE} 文件内容不是有效的列表格式。将初始化为空列表。")
                    with recurring_reminder_lock:
                        recurring_reminders = []
        else:
            logger.info(f"{RECURRING_REMINDERS_FILE} 文件未找到。将以无提醒状态启动。")
            with recurring_reminder_lock:
                recurring_reminders = []
    except json.JSONDecodeError:
        logger.error(f"解析 {RECURRING_REMINDERS_FILE} 文件 JSON 失败。将初始化为空列表。")
        with recurring_reminder_lock:
            recurring_reminders = []
    except Exception as e:
        logger.error(f"加载提醒失败: {str(e)}", exc_info=True)
        with recurring_reminder_lock:
            recurring_reminders = [] # 确保出错时列表也被初始化


def save_recurring_reminders():
    """将内存中的当前提醒列表（重复和长期一次性）保存到 JSON 文件。"""
    global recurring_reminders
    with recurring_reminder_lock:
        reminders_to_save = list(recurring_reminders)
        try:
            import store_io
            store_io.atomic_write_json(RECURRING_REMINDERS_FILE, reminders_to_save)
            logger.info(f"成功将 {len(reminders_to_save)} 条提醒保存到 {RECURRING_REMINDERS_FILE}")
        except Exception as e:
            logger.error(f"保存提醒失败: {str(e)}", exc_info=True)


def recurring_reminder_checker():
    """后台线程函数，每分钟检查是否有到期的重复或长期一次性提醒。"""
    last_checked_minute_str = None # 记录上次检查的 YYYY-MM-DD HH:MM
    while True:
        try:
            now = datetime.now()
            # 需要精确到分钟进行匹配
            current_datetime_minute_str = now.strftime("%Y-%m-%d %H:%M")
            current_time_minute_str = now.strftime("%H:%M") # 仅用于匹配每日重复

            # 仅当分钟数变化时才执行检查
            if current_datetime_minute_str != last_checked_minute_str:
                reminders_to_trigger_now = []
                reminders_to_remove_indices = [] # 记录需要删除的一次性提醒的索引

                # 在锁保护下读取当前的提醒列表副本
                with recurring_reminder_lock:
                    current_reminders_copy = list(recurring_reminders) # 创建副本

                for index, reminder in enumerate(current_reminders_copy):
                    reminder_type = reminder.get('reminder_type')
                    user_id = reminder.get('user_id')
                    content = reminder.get('content')
                    should_trigger = False

                    if reminder_type == 'recurring':
                        # 检查每日重复提醒 (HH:MM)
                        if reminder.get('time_str') == current_time_minute_str:
                            should_trigger = True
                            logger.info(f"匹配到每日重复提醒: 用户 {user_id}, 时间 {current_time_minute_str}, 内容: {content}")
                    elif reminder_type == 'one-off':
                        # 检查长期一次性提醒 (YYYY-MM-DD HH:MM)
                        if reminder.get('target_datetime_str') == current_datetime_minute_str:
                            should_trigger = True
                            # 标记此一次性提醒以便稍后删除
                            reminders_to_remove_indices.append(index)
                            logger.info(f"匹配到长期一次性提醒: 用户 {user_id}, 时间 {current_datetime_minute_str}, 内容: {content}")

                    if should_trigger:
                        reminders_to_trigger_now.append(reminder.copy()) # 添加副本到触发列表

                # --- 触发提醒 ---
                if reminders_to_trigger_now:
                    logger.info(f"当前时间 {current_datetime_minute_str}，发现 {len(reminders_to_trigger_now)} 条到期的提醒。")
                    if is_quiet_time() and not ALLOW_REMINDERS_IN_QUIET_TIME:
                        logger.info(f"处于安静时间，将抑制 {len(reminders_to_trigger_now)} 条提醒。")
                    else:
                        for reminder in reminders_to_trigger_now:
                            user_id = reminder['user_id']
                            content = reminder['content']
                            reminder_type = reminder['reminder_type'] # 获取类型用于日志和提示
                            logger.info(f"正在为用户 {user_id} 触发【{reminder_type}】提醒：{content}")

                            # 修改：不再直接调用API，而是将提醒添加到消息队列
                            try:
                                # 构造提醒消息前缀
                                if reminder_type == 'recurring':
                                    prefix = f"每日提醒：{content}"
                                else: # one-off
                                    prefix = f"一次性提醒：{content}"

                                # 将提醒添加到用户的消息队列
                                formatted_message = f"[{now.strftime('%Y-%m-%d %A %H:%M:%S')}] {prefix}"
                                
                                with queue_lock:
                                    if user_id not in user_queues:
                                        user_queues[user_id] = {
                                            'messages': [formatted_message],
                                            'sender_name': user_id,
                                            'username': user_id,
                                            'last_message_time': time.time()
                                        }
                                    else:
                                        user_queues[user_id]['messages'].append(formatted_message)
                                        user_queues[user_id]['last_message_time'] = time.time()
                                
                                logger.info(f"已将{reminder_type}提醒 '{content}' 添加到用户 {user_id} 的消息队列，用以执行联网检查流程")

                                # 保留语音通话功能（如果启用）
                                if get_dynamic_config('USE_VOICE_CALL_FOR_REMINDERS', USE_VOICE_CALL_FOR_REMINDERS):
                                    try:
                                        wx.VoiceCall(user_id)
                                        logger.info(f"通过语音通话提醒用户 {user_id} ({reminder_type}提醒)。")
                                    except Exception as voice_err:
                                        logger.error(f"语音通话提醒失败 ({reminder_type}提醒)，用户 {user_id}: {voice_err}")

                            except Exception as trigger_err:
                                logger.error(f"将提醒添加到消息队列失败，用户 {user_id}，提醒：{content}：{trigger_err}")

                # --- 删除已触发的一次性提醒 ---
                if reminders_to_remove_indices:
                    logger.info(f"准备从列表中删除 {len(reminders_to_remove_indices)} 条已触发的一次性提醒。")
                    something_removed = False
                    with recurring_reminder_lock:
                        # 从后往前删除，避免索引错乱
                        indices_to_delete_sorted = sorted(reminders_to_remove_indices, reverse=True)
                        original_length = len(recurring_reminders)
                        for index in indices_to_delete_sorted:
                            # 再次检查索引是否有效（理论上应该总是有效）
                            if 0 <= index < len(recurring_reminders):
                                removed_item = recurring_reminders.pop(index)
                                logger.debug(f"已从内存列表中删除索引 {index} 的一次性提醒: {removed_item.get('content')}")
                                something_removed = True
                            else:
                                logger.warning(f"尝试删除索引 {index} 时发现其无效（当前列表长度 {len(recurring_reminders)}）。")

                        if something_removed:
                            # 只有实际删除了内容才保存文件
                            logger.info(f"已从内存中删除 {original_length - len(recurring_reminders)} 条一次性提醒，正在保存更新后的列表...")
                            save_recurring_reminders() # 保存更新后的列表
                        else:
                            logger.info("没有实际删除任何一次性提醒（可能索引无效或列表已空）。")

                # 更新上次检查的分钟数
                last_checked_minute_str = current_datetime_minute_str

            # 休眠，接近一分钟检查一次
            time.sleep(58)

        except Exception as e:
            logger.error(f"提醒检查器循环出错: {str(e)}", exc_info=True)
            time.sleep(60) # 出错后等待时间稍长

