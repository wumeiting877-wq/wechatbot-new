# -*- coding: utf-8 -*-
"""聊天上下文 / 核心记忆 / 临时记忆。函数在 bot 宿主安装后使用其全局命名空间。"""

from __future__ import annotations

from module_install import install_exports

EXPORTS = (
    "load_chat_prompt",
    "get_user_prompt",
    "load_chat_contexts",
    "merge_context",
    "save_chat_contexts",
    "log_user_message_to_memory",
    "sanitize_user_id_for_filename",
    "get_core_memory_file_path",
    "load_core_memory_from_json",
    "save_core_memory_to_json",
    "add_memory_to_json",
    "cleanup_json_memories",
    "format_json_memories_for_prompt",
    "append_to_memory_section",
    "summarize_and_save",
    "memory_manager",
    "manage_memory_capacity",
    "manage_core_memory_capacity",
    "manage_user_memory_capacity",
    "clear_memory_temp_files",
    "clear_chat_context",
    "log_original_message_to_memory",
    "log_ai_reply_to_memory",
)


def install_into(module) -> None:
    install_exports(globals(), EXPORTS, module)


def load_chat_prompt(user_id):
    """解析 Conversation → AgentConfig → Chat Prompt。失败时抛 PromptResolveError。"""
    import agent_store
    conversations = globals().get("conversations") or []
    agent_configs = globals().get("agent_configs") or []
    mapping = globals().get("prompt_mapping") or {}
    binding = agent_store.resolve_chat_prompt(
        user_id,
        conversations=conversations,
        agents=agent_configs,
        prompt_mapping=mapping,
        root_dir=root_dir,
    )
    logger.info(
        "CHAT_PROMPT conversation_id=%s agent_config_id=%s prompt_name=%s prompt_hash=%s",
        binding.conversation_id,
        binding.agent_config_id,
        binding.prompt_name,
        binding.prompt_hash,
    )
    return binding


def get_user_prompt(user_id):
    binding = load_chat_prompt(user_id)
    prompt_content = binding.content

    # 处理记忆的上传
    if not get_dynamic_config('UPLOAD_MEMORY_TO_AI', UPLOAD_MEMORY_TO_AI):
        # 如果不上传记忆到AI，则移除所有记忆片段
        memory_marker = "## 记忆片段"
        if memory_marker in prompt_content:
            prompt_content = prompt_content.split(memory_marker, 1)[0].strip()
        return prompt_content
    
    # 上传记忆到AI时，需要合并prompt文件中的记忆和JSON文件中的记忆
    json_memories = load_core_memory_from_json(user_id)
    json_memory_content = format_json_memories_for_prompt(json_memories)
    
    # 如果有JSON记忆需要添加
    if json_memory_content:
        # 找到prompt内容的结尾，添加JSON记忆
        if prompt_content.endswith('\n'):
            combined_content = prompt_content + '\n' + json_memory_content
        else:
            combined_content = prompt_content + '\n\n' + json_memory_content
        
        logger.debug(f"为用户 {user_id} 合并了 {len(json_memories)} 条JSON记忆到prompt中")
        return combined_content
    else:
        # 没有JSON记忆，直接返回原始prompt内容
        return prompt_content
             
# 加载聊天上下文

             
# 加载聊天上下文
def load_chat_contexts(force=False):
    """从文件加载聊天上下文。文件未变化时复用内存，避免每条消息都打磁盘。"""
    global chat_contexts, _chat_contexts_mtime
    try:
        if os.path.exists(CHAT_CONTEXTS_FILE):
            mtime = os.path.getmtime(CHAT_CONTEXTS_FILE)
            if not force and chat_contexts and mtime == _chat_contexts_mtime:
                return
            with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                loaded_contexts = json.load(f)
                if isinstance(loaded_contexts, dict):
                    chat_contexts = loaded_contexts
                    _chat_contexts_mtime = mtime
                    logger.info(f"成功从 {CHAT_CONTEXTS_FILE} 加载 {len(chat_contexts)} 个用户的聊天上下文。")
                else:
                    logger.warning(f"{CHAT_CONTEXTS_FILE} 文件内容格式不正确（非字典），将使用空上下文。")
                    chat_contexts = {}
                    _chat_contexts_mtime = mtime
        else:
            logger.info(f"{CHAT_CONTEXTS_FILE} 未找到，将使用空聊天上下文启动。")
            chat_contexts = {}
            _chat_contexts_mtime = 0.0
    except json.JSONDecodeError:
        logger.error(f"解析 {CHAT_CONTEXTS_FILE} 失败，文件可能已损坏。将使用空上下文。")
        chat_contexts = {}
        _chat_contexts_mtime = 0.0
    except Exception as e:
        logger.error(f"加载聊天上下文失败: {e}", exc_info=True)
        chat_contexts = {}
        _chat_contexts_mtime = 0.0


def merge_context(context_list):
    """
    合并连续相同 role 的消息，保证 user/assistant 交替。
    """
    if not context_list:
        return []
    merged = []
    last_role = None
    buffer = []
    for item in context_list:
        role = item.get('role')
        content = item.get('content', '')
        if role == last_role:
            buffer.append(content)
        else:
            if buffer:
                merged.append({'role': last_role, 'content': '\n'.join(buffer)})
            buffer = [content]
            last_role = role
    if buffer:
        merged.append({'role': last_role, 'content': '\n'.join(buffer)})
    return merged

# 保存聊天上下文


# 保存聊天上下文
def save_chat_contexts():
    """将当前聊天上下文保存到文件。"""
    global chat_contexts, _chat_contexts_mtime
    try:
        contexts_to_save = dict(chat_contexts)
        for user in contexts_to_save:
            contexts_to_save[user] = merge_context(contexts_to_save[user])
        import store_io
        store_io.atomic_write_json(CHAT_CONTEXTS_FILE, contexts_to_save)
        try:
            _chat_contexts_mtime = os.path.getmtime(CHAT_CONTEXTS_FILE)
        except OSError:
            pass
        logger.debug(f"聊天上下文已成功保存到 {CHAT_CONTEXTS_FILE}")
    except Exception as e:
        logger.error(f"保存聊天上下文到 {CHAT_CONTEXTS_FILE} 失败: {e}", exc_info=True)


# 辅助函数：将用户消息记录到记忆日志 (如果启用)
def log_user_message_to_memory(username, original_content):
    """将用户的原始消息记录到记忆日志文件。"""
    if ENABLE_MEMORY:
        try:
            prompt_name = prompt_mapping.get(username, username)
            safe_username = sanitize_user_id_for_filename(username)
            safe_prompt_name = sanitize_user_id_for_filename(prompt_name)
            log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{safe_username}_{safe_prompt_name}_log.txt')
            log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{username}] {original_content}\n"
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            # 增强编码处理的写入
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
            except UnicodeEncodeError as e:
                logger.warning(f"UTF-8编码失败，尝试清理特殊字符: {log_file}, 错误: {e}")
                # 清理无法编码的字符
                clean_content = original_content.encode('utf-8', errors='ignore').decode('utf-8')
                clean_log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{username}] {clean_content}\n"
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(clean_log_entry)
                logger.info(f"已清理特殊字符并写入记忆日志: {log_file}")
        except Exception as write_err:
             logger.error(f"写入用户 {username} 的记忆日志失败: {write_err}")

# --- 文本指令处理 ---


# 记忆管理功能
def sanitize_user_id_for_filename(user_id):
    """将user_id转换为安全的文件名，支持中文字符"""
    import re
    import string
    
    # 如果输入为空或None，返回默认值
    if not user_id:
        return "default_user"
    
    # 移除或替换危险字符，但保留中文字符
    # 危险字符：路径分隔符、控制字符、特殊符号等
    dangerous_chars = r'[<>:"/\\|?*\x00-\x1f\x7f]'
    safe_name = re.sub(dangerous_chars, '_', user_id)
    
    # 移除开头和结尾的空格和点
    safe_name = safe_name.strip(' .')
    
    # 确保不是Windows保留名称
    windows_reserved = {
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    }
    if safe_name.upper() in windows_reserved:
        safe_name = f"user_{safe_name}"
    
    # 如果结果为空，使用默认值
    if not safe_name:
        safe_name = "default_user"
    
    # 限制长度，避免文件名过长
    if len(safe_name) > 100:  # 保守的长度限制
        # 尝试保留中文字符的完整性
        safe_name = safe_name[:100]
        # 确保不在中文字符中间截断
        if len(safe_name.encode('utf-8')) > len(safe_name):
            # 有中文字符，更保守地截断
            safe_name = safe_name[:50]
    
    return safe_name


def get_core_memory_file_path(user_id):
    """获取核心记忆JSON文件的路径"""
    safe_user_id = sanitize_user_id_for_filename(user_id)
    prompt_name = prompt_mapping.get(user_id, user_id)
    safe_prompt_name = sanitize_user_id_for_filename(prompt_name)
    core_memory_dir = os.path.join(root_dir, CORE_MEMORY_DIR)
    os.makedirs(core_memory_dir, exist_ok=True)
    return os.path.join(core_memory_dir, f'{safe_user_id}_{safe_prompt_name}_core_memory.json')


def load_core_memory_from_json(user_id):
    """从JSON文件加载核心记忆"""
    memory_file = get_core_memory_file_path(user_id)
    memories = []
    try:
        if os.path.exists(memory_file):
            with open(memory_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    memories = data
                    logger.debug(f"从JSON文件加载了 {len(memories)} 条核心记忆，用户: {user_id}")
                else:
                    logger.warning(f"核心记忆文件格式不正确，用户: {user_id}")
        else:
            logger.debug(f"核心记忆文件不存在，用户: {user_id}")
    except Exception as e:
        logger.error(f"加载核心记忆JSON文件失败，用户: {user_id}: {e}")
    return memories


def save_core_memory_to_json(user_id, memories):
    """将核心记忆保存到JSON文件"""
    memory_file = get_core_memory_file_path(user_id)
    try:
        import store_io
        store_io.atomic_write_json(memory_file, memories, indent=2)
        logger.info(f"成功保存 {len(memories)} 条核心记忆到JSON文件，用户: {user_id}")
    except Exception as e:
        logger.error(f"保存核心记忆JSON文件失败，用户: {user_id}: {e}")


def add_memory_to_json(user_id, timestamp, summary, importance):
    """向JSON文件添加一条新记忆"""
    memories = load_core_memory_from_json(user_id)
    new_memory = {
        "timestamp": timestamp,
        "summary": summary,
        "importance": importance
    }
    memories.append(new_memory)
    
    # 如果超出最大数量，进行淘汰
    if len(memories) > MAX_MEMORY_NUMBER:
        memories = cleanup_json_memories(memories)
    
    save_core_memory_to_json(user_id, memories)


def cleanup_json_memories(memories):
    """对JSON格式的记忆进行淘汰处理"""
    if len(memories) <= MAX_MEMORY_NUMBER:
        return memories
    
    now = datetime.now()
    memory_scores = []
    
    for memory in memories:
        try:
            timestamp = memory.get('timestamp', '')
            importance = memory.get('importance', 3)
            
            # 尝试解析时间戳
            parsed_time = None
            formats = [
                "%Y-%m-%d %A %H:%M:%S",
                "%Y-%m-%d %A %H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M"
            ]
            
            for fmt in formats:
                try:
                    parsed_time = datetime.strptime(timestamp, fmt)
                    break
                except ValueError:
                    continue
            
            if parsed_time:
                time_diff = (now - parsed_time).total_seconds()
            else:
                logger.warning(f"无法解析JSON记忆时间戳: {timestamp}")
                time_diff = 0
            
            # 计算评分：0.6 * 重要度 - 0.4 * (时间差小时数)
            score = 0.6 * importance - 0.4 * (time_diff / 3600)
            memory_scores.append(score)
            
        except Exception as e:
            logger.warning(f"处理JSON记忆项时出错: {e}")
            memory_scores.append(0)  # 默认分数
    
    # 获取保留索引（按分数降序，时间升序）
    sorted_indices = sorted(range(len(memory_scores)), 
                          key=lambda k: (-memory_scores[k], memories[k].get('timestamp', '')))
    keep_indices = set(sorted_indices[:MAX_MEMORY_NUMBER])
    
    # 保留高分记忆
    cleaned_memories = [memories[i] for i in sorted(keep_indices)]
    logger.info(f"JSON记忆淘汰：从 {len(memories)} 条清理为 {len(cleaned_memories)} 条")
    
    return cleaned_memories


def format_json_memories_for_prompt(memories):
    """将JSON格式的记忆转换为prompt格式"""
    if not memories:
        return ""
    
    formatted_lines = []
    for memory in memories:
        timestamp = memory.get('timestamp', '')
        summary = memory.get('summary', '')
        importance = memory.get('importance', 3)
        
        formatted_lines.append(f"""## 记忆片段 [{timestamp}]
**重要度**: {importance}
**摘要**: {summary}

""")
    
    return ''.join(formatted_lines)


def append_to_memory_section(user_id, content):
    """将内容追加到用户prompt文件的记忆部分"""
    try:
        prompts_dir = os.path.join(root_dir, 'prompts')
        # 注意：这里应该使用prompt_name而不是user_id作为文件名
        prompt_name = prompt_mapping.get(user_id, user_id)
        safe_prompt_name = sanitize_user_id_for_filename(prompt_name)
        user_file = os.path.join(prompts_dir, f'{safe_prompt_name}.md')
        
        # 确保用户文件存在
        if not os.path.exists(user_file):
            raise FileNotFoundError(f"用户文件 {safe_prompt_name}.md 不存在")

        # 读取并处理文件内容
        with open(user_file, 'r+', encoding='utf-8') as file:
            lines = file.readlines()
            
            # 查找记忆插入点
            memory_marker = "开始更新："
            insert_index = next((i for i, line in enumerate(lines) if memory_marker in line), -1)

            # 如果没有找到标记，追加到文件末尾
            if (insert_index == -1):
                insert_index = len(lines)
                lines.append(f"\n{memory_marker}\n")
                logger.info(f"在用户文件 {user_id}.md 中添加记忆标记")

            # 插入记忆内容
            current_date = datetime.now().strftime("%Y-%m-%d")
            new_content = f"\n### {current_date}\n{content}\n"

            # 写入更新内容
            lines.insert(insert_index + 1, new_content)
            file.seek(0)
            file.writelines(lines)
            file.truncate()

    except PermissionError as pe:
        logger.error(f"文件权限拒绝: {pe} (尝试访问 {user_file})")
    except IOError as ioe:
        logger.error(f"文件读写错误: {ioe} (路径: {os.path.abspath(user_file)})")
    except Exception as e:
        logger.error(f"记忆存储失败: {str(e)}", exc_info=True)
        raise  # 重新抛出异常供上层处理
    except FileNotFoundError as e:
        logger.error(f"文件未找到: {str(e)}")
        raise


def summarize_and_save(user_id, skip_check=False):
    """总结聊天记录并存储记忆
    
    Args:
        user_id: 用户ID
        skip_check: 是否跳过记忆条目数量检查，用于手动触发的总结命令
    """
    log_file = None
    temp_file = None
    backup_file = None
    try:
        # --- 前置检查 ---
        prompt_name = prompt_mapping.get(user_id, user_id)  # 获取配置的prompt名
        safe_user_id = sanitize_user_id_for_filename(user_id)
        safe_prompt_name = sanitize_user_id_for_filename(prompt_name)
        log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{safe_user_id}_{safe_prompt_name}_log.txt')
        if not os.path.exists(log_file):
            logger.warning(f"日志文件不存在: {log_file}")
            return
        if os.path.getsize(log_file) == 0:
            logger.info(f"空日志文件: {log_file}")
            return

        # --- 读取日志 (增强编码处理) ---
        logs = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = [line.strip() for line in f if line.strip()]
        except UnicodeDecodeError as e:
            logger.warning(f"UTF-8解码失败，尝试其他编码格式: {log_file}, 错误: {e}")
            # 尝试常见的编码格式
            for encoding in ['gbk', 'gb2312', 'latin-1', 'cp1252']:
                try:
                    with open(log_file, 'r', encoding=encoding) as f:
                        logs = [line.strip() for line in f if line.strip()]
                    logger.info(f"成功使用 {encoding} 编码读取文件: {log_file}")
                    # 重新以UTF-8编码保存文件
                    with open(log_file, 'w', encoding='utf-8') as f:
                        for log in logs:
                            f.write(log + '\n')
                    logger.info(f"已将文件重新转换为UTF-8编码: {log_file}")
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            else:
                # 所有编码都失败，创建备份并重置文件
                backup_log_file = f"{log_file}.corrupted_{int(time.time())}"
                try:
                    shutil.copy(log_file, backup_log_file)
                    logger.error(f"无法解码日志文件，已备份到: {backup_log_file}")
                except Exception as backup_err:
                    logger.error(f"备份损坏文件失败: {backup_err}")
                
                # 重置为空文件
                with open(log_file, 'w', encoding='utf-8') as f:
                    f.write("")
                logger.warning(f"已重置损坏的日志文件: {log_file}")
                return
        except Exception as e:
            logger.error(f"读取日志文件时发生未知错误: {log_file}, 错误: {e}")
            return
            
        # 修改检查条件：仅检查是否达到最小处理阈值（除非跳过检查）
        if not skip_check and len(logs) < MAX_MESSAGE_LOG_ENTRIES:
            logger.info(f"日志条目不足（{len(logs)}条），未触发记忆总结。")
            return

        # --- 生成总结 ---
        # 修改为使用全部日志内容
        full_logs = '\n'.join(logs)  # 变量名改为更明确的full_logs
        summary_prompt = f"请以{prompt_name}的视角，用中文总结与{user_id}的对话，提取重要信息总结为一段话作为记忆片段（直接回复一段话）：\n{full_logs}"
        
        # 根据配置选择使用辅助模型或主模型进行记忆总结
        if USE_ASSISTANT_FOR_MEMORY_SUMMARY and ENABLE_ASSISTANT_MODEL:
            logger.info(f"使用辅助模型为用户 {user_id} 生成记忆总结")
            summary = get_assistant_response(summary_prompt, "memory_summary", is_summary=True, allow_main_fallback=True)
        else:
            logger.info(f"使用主模型为用户 {user_id} 生成记忆总结")
            summary = get_deepseek_response(summary_prompt, "system", store_context=False, is_summary=True)

        # 添加清洗，匹配可能存在的**重要度**或**摘要**字段以及##记忆片段 [%Y-%m-%d %A %H:%M]或[%Y-%m-%d %H:%M]或[%Y-%m-%d %H:%M:%S]或[%Y-%m-%d %A %H:%M:%S]格式的时间戳
        summary = re.sub(
            r'\*{0,2}(重要度|摘要)\*{0,2}[\s:]*\d*[\.]?\d*[\s\\]*|## 记忆片段 \[\d{4}-\d{2}-\d{2}( [A-Za-z]+)? \d{2}:\d{2}(:\d{2})?\]',
            '',
            summary,
            flags=re.MULTILINE
        ).strip()

        # --- 评估重要性 ---
        importance_prompt = f"为以下记忆的重要性评分（1-5，直接回复数字）：\n{summary}"
        
        # 根据配置选择使用辅助模型或主模型进行重要性评估
        if USE_ASSISTANT_FOR_MEMORY_SUMMARY and ENABLE_ASSISTANT_MODEL:
            logger.info(f"使用辅助模型为用户 {user_id} 进行重要性评估")
            importance_response = get_assistant_response(importance_prompt, "memory_importance", is_summary=True, allow_main_fallback=True)
        else:
            logger.info(f"使用主模型为用户 {user_id} 进行重要性评估")
            importance_response = get_deepseek_response(importance_prompt, "system", store_context=False, is_summary=True)
        
        # 强化重要性提取逻辑
        importance_match = re.search(r'[1-5]', importance_response)
        if importance_match:
            importance = min(max(int(importance_match.group()), 1), 5)  # 确保1-5范围
        else:
            importance = 3  # 默认值
            logger.warning(f"无法解析重要性评分，使用默认值3。原始响应：{importance_response}")

        # --- 存储记忆 ---
        current_time = datetime.now().strftime("%Y-%m-%d %A %H:%M")
        
        # 根据配置选择存储方式
        if get_dynamic_config('SAVE_MEMORY_TO_SEPARATE_FILE', SAVE_MEMORY_TO_SEPARATE_FILE):
            # 保存到JSON文件
            logger.info(f"将记忆保存到JSON文件，用户: {user_id}")
            add_memory_to_json(user_id, current_time, summary, importance)
        else:
            # 保存到prompt文件
            logger.info(f"将记忆保存到prompt文件，用户: {user_id}")
            # 修正1：增加末尾换行
            memory_entry = f"""## 记忆片段 [{current_time}]
**重要度**: {importance}
**摘要**: {summary}

"""  # 注意这里有两个换行

            prompt_name = prompt_mapping.get(user_id, user_id)
            prompts_dir = os.path.join(root_dir, 'prompts')
            os.makedirs(prompts_dir, exist_ok=True)

            user_prompt_file = os.path.join(prompts_dir, f'{prompt_name}.md')
            temp_file = f"{user_prompt_file}.tmp"
            backup_file = f"{user_prompt_file}.bak"

            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    if os.path.exists(user_prompt_file):
                        with open(user_prompt_file, 'r', encoding='utf-8') as src:
                            f.write(src.read().rstrip() + '\n\n')  # 修正2：规范化原有内容结尾
                
                    # 写入预格式化的内容
                    f.write(memory_entry)  # 不再重复生成字段

                # 步骤2：备份原文件
                if os.path.exists(user_prompt_file):
                    shutil.copyfile(user_prompt_file, backup_file)

                # 步骤3：替换文件
                shutil.move(temp_file, user_prompt_file)

            except Exception as e:
                # 异常恢复流程
                if os.path.exists(backup_file):
                    shutil.move(backup_file, user_prompt_file)
                raise

        # --- 清理日志 ---
        with open(log_file, 'w', encoding='utf-8') as f:
            f.truncate()

    except Exception as e:
        logger.error(f"记忆保存失败: {str(e)}", exc_info=True)
    finally:
        # 清理临时文件
        for f in [temp_file, backup_file]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception as e:
                    logger.error(f"清理临时文件失败: {str(e)}")


def memory_manager():
    """记忆管理定时任务"""
    while True:
        try:
            # 检查所有监听用户
            for user in user_names:
                prompt_name = prompt_mapping.get(user, user)  # 获取配置的prompt名
                log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user}_{prompt_name}_log.txt')
                
                try:
                    # 根据配置调用对应的记忆容量管理函数
                    manage_user_memory_capacity(user)
                except UnicodeDecodeError as ude:
                    logger.error(f"用户 {user} 的记忆文件编码异常: {str(ude)}")
                    logger.info(f"跳过用户 {user} 的内存管理，等待下一轮检查")
                    continue
                except Exception as e:
                    logger.error(f"用户 {user} 内存管理失败: {str(e)}")
                    continue

                if os.path.exists(log_file):
                    try:
                        # 增强编码处理的行数统计
                        line_count = 0
                        try:
                            with open(log_file, 'r', encoding='utf-8') as f:
                                line_count = sum(1 for _ in f)
                        except UnicodeDecodeError as ude:
                            logger.warning(f"UTF-8解码失败，尝试修复编码后重新统计: {log_file}, 错误: {ude}")
                            # 读取全部内容（宽容解码）并修复为纯 UTF-8
                            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                                content = f.read()
                            backup_file = f"{log_file}.bak_{int(time.time())}"
                            try:
                                shutil.copy(log_file, backup_file)
                                with open(log_file, 'w', encoding='utf-8') as f:
                                    f.write(content)
                                logger.info(f"已修复日志文件编码为UTF-8: {log_file} (备份: {backup_file})")
                            except Exception as save_err:
                                logger.error(f"修复日志文件编码失败: {log_file}, 错误: {save_err}")
                            with open(log_file, 'r', encoding='utf-8') as f:
                                line_count = sum(1 for _ in f)
                                
                        if line_count >= MAX_MESSAGE_LOG_ENTRIES:
                            summarize_and_save(user)
                    except Exception as file_err:
                        logger.error(f"处理用户 {user} 的日志文件时出错: {file_err}")
                        continue
    
        except Exception as e:
            logger.error(f"记忆管理异常: {str(e)}")
        finally:
            time.sleep(60)  # 每分钟检查一次


def manage_memory_capacity(user_file):
    """记忆淘汰机制 - 处理prompt文件中的记忆清理"""
    # 允许重要度缺失（使用可选捕获组）
    MEMORY_SEGMENT_PATTERN = r'## 记忆片段 \[(.*?)\]\n(?:\*{2}重要度\*{2}: (\d*)\n)?\*{2}摘要\*{2}:(.*?)(?=\n## 记忆片段 |\Z)'
    try:
        # 增强编码处理的文件读取
        content = None
        try:
            with open(user_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError as e:
            logger.warning(f"UTF-8解码失败，尝试其他编码格式: {user_file}, 错误: {e}")
            # 尝试常见的编码格式
            for encoding in ['gbk', 'gb2312', 'latin-1', 'cp1252']:
                try:
                    with open(user_file, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.info(f"成功使用 {encoding} 编码读取用户文件: {user_file}")
                    # 重新以UTF-8编码保存文件
                    backup_file = f"{user_file}.bak_{int(time.time())}"
                    try:
                        shutil.copy(user_file, backup_file)
                        with open(user_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                        logger.info(f"已将用户文件重新转换为UTF-8编码: {user_file} (备份: {backup_file})")
                    except Exception as save_err:
                        logger.error(f"重新保存用户文件失败: {save_err}")
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            else:
                # 所有编码都失败
                backup_file = f"{user_file}.corrupted_{int(time.time())}"
                try:
                    shutil.copy(user_file, backup_file)
                    logger.error(f"无法解码用户文件，已备份到: {backup_file}")
                except Exception as backup_err:
                    logger.error(f"备份损坏用户文件失败: {backup_err}")
                logger.error(f"用户文件编码损坏，跳过记忆管理: {user_file}")
                return
        
        if content is None:
            logger.error(f"无法读取用户文件内容: {user_file}")
            return
        
        # 解析记忆片段
        segments = re.findall(MEMORY_SEGMENT_PATTERN, content, re.DOTALL)
        if len(segments) <= MAX_MEMORY_NUMBER:
            return

        # 构建评分体系
        now = datetime.now()
        memory_scores = []
        for timestamp, importance, _ in segments:
            try:
                # 尝试多种时间格式，支持新旧格式
                formats = [
                    "%Y-%m-%d %A %H:%M:%S",  # 新格式，带星期和秒
                    "%Y-%m-%d %A %H:%M",     # 新格式，带星期但没有秒
                    "%Y-%m-%d %H:%M:%S",     # 带秒但没有星期
                    "%Y-%m-%d %H:%M"         # 原始格式
                ]
                
                parsed_time = None
                for fmt in formats:
                    try:
                        parsed_time = datetime.strptime(timestamp, fmt)
                        break
                    except ValueError:
                        continue
                
                if parsed_time:
                    time_diff = (now - parsed_time).total_seconds()
                else:
                    # 如果所有格式都解析失败
                    logger.warning(f"无法解析时间戳: {timestamp}")
                    time_diff = 0
            except Exception as e:
                logger.warning(f"时间戳解析错误: {str(e)}")
                time_diff = 0
                
            # 处理重要度缺失，默认值为3
            importance_value = int(importance) if importance else 3
            score = 0.6 * importance_value - 0.4 * (time_diff / 3600)
            memory_scores.append(score)

        # 获取保留索引
        sorted_indices = sorted(range(len(memory_scores)),
                              key=lambda k: (-memory_scores[k], segments[k][0]))
        keep_indices = set(sorted_indices[:MAX_MEMORY_NUMBER])

        # 重建内容
        memory_blocks = re.split(r'(?=## 记忆片段 \[)', content)
        new_content = []
        
        # 解析时处理缺失值
        for idx, block in enumerate(memory_blocks):
            if idx == 0:
                new_content.append(block)
                continue
            try:
                # 显式关联 memory_blocks 与 segments 的索引
                segment_idx = idx - 1
                if segment_idx < len(segments) and segment_idx in keep_indices:
                    new_content.append(block)
            except Exception as e:
                logger.warning(f"跳过无效记忆块: {str(e)}")
                continue

        # 原子写入
        with open(f"{user_file}.tmp", 'w', encoding='utf-8') as f:
            f.write(''.join(new_content).strip())
        
        shutil.move(f"{user_file}.tmp", user_file)
        logger.info(f"成功清理prompt文件中的记忆")

    except Exception as e:
        logger.error(f"记忆整理失败: {str(e)}")


def manage_core_memory_capacity(user_id):
    """管理JSON文件中的核心记忆容量"""
    try:
        memories = load_core_memory_from_json(user_id)
        if len(memories) > MAX_MEMORY_NUMBER:
            logger.info(f"用户 {user_id} 的JSON记忆超过容量限制，开始清理")
            cleaned_memories = cleanup_json_memories(memories)
            save_core_memory_to_json(user_id, cleaned_memories)
            logger.info(f"用户 {user_id} 的JSON记忆清理完成")
    except Exception as e:
        logger.error(f"管理用户 {user_id} 的JSON记忆容量失败: {e}")


def manage_user_memory_capacity(user):
    """根据配置管理用户的记忆容量（prompt文件或JSON文件）"""
    try:
        if get_dynamic_config('SAVE_MEMORY_TO_SEPARATE_FILE', SAVE_MEMORY_TO_SEPARATE_FILE):
            # 清理JSON文件中的记忆
            manage_core_memory_capacity(user)
        else:
            # 清理prompt文件中的记忆
            prompt_name = prompt_mapping.get(user, user)
            user_prompt_file = os.path.join(root_dir, 'prompts', f'{prompt_name}.md')
            manage_memory_capacity(user_prompt_file)
    except Exception as e:
        logger.error(f"管理用户 {user} 记忆容量失败: {e}")


def clear_memory_temp_files(user_id):
    """清除指定用户的Memory_Temp文件"""
    try:
        logger.warning(f"已开启自动清除Memory_Temp文件功能，尝试清除用户 {user_id} 的Memory_Temp文件")
        prompt_name = prompt_mapping.get(user_id, user_id)
        safe_user_id = sanitize_user_id_for_filename(user_id)
        safe_prompt_name = sanitize_user_id_for_filename(prompt_name)
        log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{safe_user_id}_{safe_prompt_name}_log.txt')
        if os.path.exists(log_file):
            os.remove(log_file)
            logger.warning(f"已清除用户 {user_id} 的Memory_Temp文件: {log_file}")
    except Exception as e:
        logger.error(f"清除Memory_Temp文件失败: {str(e)}")


def clear_chat_context(user_id):
    """清除指定用户的聊天上下文"""
    logger.info(f"已开启自动清除上下文功能，尝试清除用户 {user_id} 的聊天上下文")
    try:
        with queue_lock:
            if user_id in chat_contexts:
                del chat_contexts[user_id]
                save_chat_contexts()
                logger.warning(f"已清除用户 {user_id} 的聊天上下文")
    except Exception as e:
        logger.error(f"清除聊天上下文失败: {str(e)}")


def log_original_message_to_memory(user_id, message_content):
    """将设置提醒的原始用户消息记录到记忆日志文件（如果启用了记忆功能）。"""
    if ENABLE_MEMORY: # 检查是否启用了记忆功能
        try:
            # 获取用户对应的 prompt 文件名（或用户昵称）
            prompt_name = prompt_mapping.get(user_id, user_id)
            safe_user_id = sanitize_user_id_for_filename(user_id)
            safe_prompt_name = sanitize_user_id_for_filename(prompt_name)
            # 构建日志文件路径
            log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{safe_user_id}_{safe_prompt_name}_log.txt')
            # 准备日志条目，记录原始用户消息
            log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{user_id}] {message_content}\n"
            # 确保目录存在
            os.makedirs(os.path.dirname(log_file), exist_ok=True)

            # 增强编码处理的写入
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
            except UnicodeEncodeError as e:
                logger.warning(f"UTF-8编码失败，尝试清理特殊字符: {log_file}, 错误: {e}")
                # 清理无法编码的字符
                clean_content = message_content.encode('utf-8', errors='ignore').decode('utf-8')
                clean_log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{user_id}] {clean_content}\n"
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(clean_log_entry)
                logger.info(f"已清理特殊字符并写入提醒记忆日志: {log_file}")
        except Exception as write_err:
            logger.error(f"写入用户 {user_id} 的提醒设置记忆日志失败: {write_err}")



def log_ai_reply_to_memory(username, reply_part):
    """将 AI 的回复部分记录到用户的记忆日志文件中。"""
    if not ENABLE_MEMORY:  # 双重检查是否意外调用
         return
    try:
        prompt_name = prompt_mapping.get(username, username)  # 使用配置的提示名作为 AI 身份
        log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{username}_{prompt_name}_log.txt')
        log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{prompt_name}] {reply_part}\n"

        # 确保日志目录存在
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # 增强编码处理的写入
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except UnicodeEncodeError as e:
            logger.warning(f"UTF-8编码失败，尝试清理特殊字符: {log_file}, 错误: {e}")
            # 清理无法编码的字符
            clean_reply = reply_part.encode('utf-8', errors='ignore').decode('utf-8')
            clean_log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{prompt_name}] {clean_reply}\n"
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(clean_log_entry)
            logger.info(f"已清理特殊字符并写入AI回复记忆日志: {log_file}")
    except Exception as log_err:
        logger.error(f"记录 AI 回复到记忆日志失败，用户 {username}: {log_err}")

