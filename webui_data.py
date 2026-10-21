# -*- coding: utf-8 -*-
"""Prompt / 会话上下文 / 核心记忆 WebUI 路由。安装进 config_editor 宿主后注册。"""

from __future__ import annotations

import os
import re

from module_install import install_exports

DATA_ROUTES = (
    ("/edit_prompt/<filename>", "edit_prompt", ["GET", "POST"]),
    ("/create_prompt", "create_prompt", ["GET", "POST"]),
    ("/delete_prompt/<filename>", "delete_prompt", ["POST"]),
    ("/generate_prompt", "generate_prompt", ["POST"]),
    ("/api/prompts", "api_list_prompts", ["GET"]),
    ("/api/get_chat_context_users", "api_get_chat_context_users", ["GET"]),
    ("/clear_chat_context/<username>", "clear_chat_context", ["POST"]),
    ("/api/get_chat_context/<username>", "get_user_chat_context", ["GET"]),
    ("/api/save_chat_context/<username>", "save_user_chat_context", ["POST"]),
    ("/api/get_core_memory_files", "get_core_memory_files", ["GET"]),
    ("/api/get_core_memory/<filename>", "get_core_memory", ["GET"]),
    ("/api/save_core_memory/<filename>", "save_core_memory", ["POST"]),
    ("/api/delete_core_memory/<filename>", "delete_core_memory", ["DELETE"]),
)


EXPORTS = (
    "safe_filename",
    "list_prompt_names",
    "api_list_prompts",
    "edit_prompt",
    "create_prompt",
    "delete_prompt",
    "generate_prompt",
    "api_get_chat_context_users",
    "clear_chat_context",
    "get_user_chat_context",
    "save_user_chat_context",
    "get_core_memory_files",
    "get_core_memory",
    "save_core_memory",
    "delete_core_memory",
)


def install_into(module) -> None:
    install_exports(globals(), EXPORTS, module)


def register_data_routes(app, login_required, g):
    """g 为 config_editor 模块。"""
    install_into(g)
    for path, name, methods in DATA_ROUTES:
        app.add_url_rule(path, endpoint=name, view_func=login_required(getattr(g, name)), methods=methods)


# 替换secure_filename的汉字过滤逻辑
def safe_filename(filename):
    # 只保留汉字、字母、数字、下划线和点，其他字符替换为_
    filename = re.sub(r'[^\w\u4e00-\u9fff.]', '_', filename)
    # 防止路径穿越
    filename = filename.replace('../', '_').replace('/', '_')
    return filename


def list_prompt_names():
    """读取 Prompt 管理同一数据源：prompts 目录下的 .md 文件名（不含后缀）。"""
    prompt_dir = os.path.abspath('prompts')
    if not os.path.exists(prompt_dir):
        os.makedirs(prompt_dir)
    names = []
    for filename in os.listdir(prompt_dir):
        if not filename.endswith('.md'):
            continue
        filepath = os.path.join(prompt_dir, filename)
        if os.path.isfile(filepath):
            names.append(filename[:-3])
    names.sort()
    return names


def api_list_prompts():
    """供监听对象 Prompt 下拉框使用，与 Prompt 管理共用 prompts 目录。"""
    try:
        prompts = list_prompt_names()
        return jsonify({'ok': True, 'prompts': prompts})
    except Exception as e:
        app.logger.error(f"获取 Prompt 列表失败: {e}")
        return jsonify({'ok': False, 'error': 'Prompt 加载失败', 'prompts': []}), 500


def edit_prompt(filename):
    safe_dir = os.path.abspath('prompts')
    # 从path中移除.md后缀，如果存在的话，因为safe_filename会处理
    if filename.endswith('.md'):
        filename_no_ext = filename[:-3]
    else:
        filename_no_ext = filename
    
    # 使用 safe_filename 处理，并确保.md后缀
    # 注意：前端JS在调用此接口时，filename参数应该是包含.md的
    # 所以这里的safe_filename应该针对传入的filename
    processed_filename = safe_filename(filename) 
    filepath = _safe_file_path(safe_dir, processed_filename)
    if not filepath:
        return jsonify({'error': '无效的文件路径'}), 400

    if request.method == 'POST':
        content = request.form.get('content', '')
        new_filename_from_form = request.form.get('filename', '').strip()

        if not new_filename_from_form.endswith('.md'):
            new_filename_from_form += '.md'
        new_filename_safe = safe_filename(new_filename_from_form)
        new_filepath = _safe_file_path(safe_dir, new_filename_safe)
        if not new_filepath:
            return "无效的文件路径", 400

        try:
            # 如果文件名改变了
            if new_filename_safe != processed_filename:
                return jsonify({
                    'ok': False,
                    'error': 'PROMPT_RENAME_FORBIDDEN',
                    'message': '禁止直接重命名 Prompt，请另存为新 Prompt。',
                    'detail': 'rename is not supported in phase 1',
                }), 400

            # 写入内容
            atomic_write_text(filepath, content)
            prompt_name = new_filename_safe[:-3] if new_filename_safe.endswith('.md') else new_filename_safe
            try:
                import agent_store
                cfg = parse_config()
                agents = cfg.get('AGENT_CONFIGS') or []
                agent_store.update_agents_prompt_hash(agents, prompt_name, content)
                save_structured_config({'AGENT_CONFIGS': agents})
            except Exception as hash_err:
                app.logger.warning(f"更新 Prompt hash 失败: {hash_err}")
            log_audit("save_prompt", detail=f"保存 Prompt {new_filename_safe}")
            # 修改后，不需要重定向到 prompt_list，前端会刷新或处理
            return jsonify({'status': 'success', 'message': 'Prompt已保存'}), 200
        except Exception as e:
            app.logger.error(f"保存Prompt失败: {str(e)}")
            return f"保存失败: {str(e)}", 500

    # GET 请求部分: 返回JSON数据
    try:
        if not os.path.exists(filepath): # 确保文件存在
            return jsonify({'error': '文件不存在'}), 404
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        # 返回JSON，而不是渲染模板
        return jsonify({'filename': processed_filename, 'content': content})
    except FileNotFoundError:
        return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        app.logger.error(f"读取Prompt失败: {str(e)}")
        return jsonify({'error': f'读取Prompt失败: {str(e)}'}), 500


def create_prompt():
    if request.method == 'POST':
        filename = request.form.get('filename', '').strip()
        content = request.form.get('content', '')
        
        if not filename:
            return "文件名不能为空", 400 # 返回错误状态码
            
        if not filename.endswith('.md'):
            filename += '.md'
        filename = safe_filename(filename) # 应用安全文件名处理
        
        filepath = _safe_file_path(os.path.abspath('prompts'), filename)
        if not filepath:
            return "无效的文件路径", 400
        if os.path.exists(filepath):
            return "文件已存在", 409 # 409 Conflict 更合适
            
        try:
            if not os.path.exists('prompts'): # 确保目录存在
                os.makedirs('prompts')
            atomic_write_text(filepath, content)
            log_audit("create_prompt", detail=f"创建 Prompt {filename}")
            # 返回成功JSON，而不是重定向
            return jsonify({'status': 'success', 'message': 'Prompt已创建'}), 201 # 201 Created
        except Exception as e:
            app.logger.error(f"创建Prompt失败: {str(e)}")
            return f"创建失败: {str(e)}", 500
    
    return "此端点用于POST创建Prompt，或GET请求已被整合处理。", 405 # Method Not Allowed for GET


def delete_prompt(filename):
    safe_dir = os.path.abspath('prompts')
    filepath = _safe_file_path(safe_dir, safe_filename(filename))
    
    if filepath and os.path.isfile(filepath) and _is_path_inside(safe_dir, filepath):
        prompt_name = os.path.basename(filepath)
        if prompt_name.endswith('.md'):
            prompt_name = prompt_name[:-3]
        try:
            import agent_store
            cfg = parse_config()
            agents = cfg.get('AGENT_CONFIGS') or []
            used_by = agent_store.agents_using_prompt(agents, prompt_name)
            listen_hits = agent_store.listen_list_using_prompt(cfg.get('LISTEN_LIST') or [], prompt_name)
            if used_by or listen_hits:
                names = [str(item.get('name') or item.get('id') or '') for item in used_by]
                detail = '、'.join([n for n in names if n]) or prompt_name
                return jsonify({
                    'ok': False,
                    'error': 'PROMPT_IN_USE',
                    'message': '该 Prompt 正被以下 Agent 使用，不能删除。',
                    'detail': detail,
                    'agents': names,
                }), 409
            os.remove(filepath)
            log_audit("delete_prompt", detail=f"删除 Prompt {filename}")
            return '', 204
        except Exception as e:
            return str(e), 500
    return "无效文件", 400


def generate_prompt():
    try:
        # 从config.py获取配置
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL
        
        client = openai.OpenAI(
            base_url=DEEPSEEK_BASE_URL,
            api_key=DEEPSEEK_API_KEY
        )
        
        prompt = request.json.get('prompt', '')
        FixedPrompt = (
            "\n请严格按照以下格式生成提示词（仅参考以下格式，将...替换为合适的内容，不要输出其他多余内容）。"
            "\n注意：仅在<# 输出示例>部分需要输出以'\\'进行分隔的短句，且不输出逗号和句号，其它部分应当正常输出。"
            "\n\n# 任务"
            "\n你需要扮演指定角色，根据角色的经历，模仿她的语气进行线上的日常对话。"
            "\n\n# 角色"
            "\n你将扮演...。"
            "\n\n# 外表"
            "\n...。"
            "\n\n# 经历"
            "\n...。"
            "\n\n# 性格"
            "\n...。"
            "\n# 输出示例"
            "\n...\\...\\..."
            "\n...\\..."
            "\n\n# 喜好"
            "\n...。\n"
        )  # 固定提示词
        
        config = parse_config()
        temperature = config.get('TEMPERATURE', 0.7)

        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{
            "role": "user",
            "content": prompt + FixedPrompt
            }],
            temperature=temperature,
            max_tokens=5000
        )
        
        reply = completion.choices[0].message.content
        if "</think>" in reply:
            reply = reply.split("</think>", 1)[1].strip()

        return jsonify({
            'result': reply
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 获取所有提醒


def api_get_chat_context_users():
    users = get_chat_context_users()
    return jsonify({'users': users})


def clear_chat_context(username):
    """清除指定用户的聊天上下文"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return jsonify({'status': 'error', 'message': '聊天上下文文件不存在'}), 404

    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            with open(CHAT_CONTEXTS_FILE, 'r+', encoding='utf-8') as f:
                data = json.load(f)
                if username in data:
                    del data[username]
                    f.seek(0) # 回到文件开头
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    f.truncate() # 删除剩余内容
                    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的聊天上下文已清除"})
                else:
                    return jsonify({'status': 'error', 'message': f"用户 '{username}' 未找到"}), 404
        except (json.JSONDecodeError, IOError) as e:
            app.logger.error(f"处理 chat_contexts.json 失败: {e}")
            return jsonify({'status': 'error', 'message': '处理聊天上下文文件失败'}), 500

# 聊天上下文编辑API


# 聊天上下文编辑API
def get_user_chat_context(username):
    """获取指定用户的聊天上下文"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return jsonify({'error': '聊天上下文文件未找到'}), 404

    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                contexts = json.load(f)
            user_context = contexts.get(username)
            if user_context is None:
                return jsonify({'error': f"用户 '{username}' 在上下文中不存在"}), 404
            pretty_context = json.dumps(user_context, ensure_ascii=False, indent=4)
            return jsonify({'status': 'success', 'context': pretty_context})
        except (json.JSONDecodeError, IOError) as e:
            app.logger.error(f"读取或解析聊天上下文文件失败: {e}")
            return jsonify({'error': f'读取或解析文件失败: {e}'}), 500


def save_user_chat_context(username):
    """保存指定用户修改后的聊天上下文，强制合并连续user消息，确保user→assistant结构"""
    if bot_process and bot_process.poll() is not None:
        return jsonify({'error': '程序正在运行，请先停止再保存上下文'}), 400
    data = request.get_json()
    if not data or 'context' not in data:
        return jsonify({'status': 'error', 'message': '请求无效，缺少 "context" 字段'}), 400
    new_context_str = data['context']
    try:
        new_context_data = json.loads(new_context_str)
        if not isinstance(new_context_data, list):
            raise ValueError("上下文数据必须是一个JSON数组 (list)")
        # --- 强制合并连续user，保证user→assistant结构 ---
        merged_context = []
        user_buffer = []
        for item in new_context_data:
            if item.get('role') == 'user':
                user_buffer.append(item.get('content', ''))
            elif item.get('role') == 'assistant':
                if user_buffer:
                    merged_context.append({'role': 'user', 'content': '\n'.join(user_buffer)})
                    user_buffer = []
                merged_context.append(item)
        if user_buffer:
            merged_context.append({'role': 'user', 'content': '\n'.join(user_buffer)})
        # --- END ---
    except (json.JSONDecodeError, ValueError) as e:
        return jsonify({'status': 'error', 'message': f'格式错误: {str(e)}'}), 400
    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            if not os.path.exists(CHAT_CONTEXTS_FILE):
                return jsonify({'status': 'error', 'message': '聊天上下文文件未找到'}), 404
            with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                all_contexts = json.load(f)
            if username not in all_contexts:
                return jsonify({'status': 'error', 'message': '用户在上下文中不存在'}), 404
            all_contexts[username] = merged_context
            atomic_write_json(CHAT_CONTEXTS_FILE, all_contexts)
        except Exception as e:
            app.logger.error(f"保存聊天上下文失败: {e}")
            return jsonify({'status': 'error', 'message': f'保存失败: {str(e)}'}), 500
    log_audit("save_chat_context", detail=f"保存会话上下文 {username}")
    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的上下文已更新"})

def get_core_memory_files():
    """获取核心记忆文件列表"""
    try:
        # 从配置中获取核心记忆目录
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        
        # 确保目录存在
        os.makedirs(core_memory_dir, exist_ok=True)
        
        files = []
        if os.path.exists(core_memory_dir):
            for filename in os.listdir(core_memory_dir):
                if filename.endswith('_core_memory.json'):
                    file_path = _safe_file_path(core_memory_dir, filename)
                    if not file_path:
                        continue
                    try:
                        # 读取文件获取记忆片段数量
                        with open(file_path, 'r', encoding='utf-8') as f:
                            memories = json.load(f)
                        
                        memory_count = len(memories) if isinstance(memories, list) else 0
                        
                        # 获取文件修改时间
                        mtime = os.path.getmtime(file_path)
                        last_modified = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                        
                        # 从文件名提取显示名称
                        display_name = filename.replace('_core_memory.json', '').replace('_', ' - ')
                        
                        files.append({
                            'filename': filename,
                            'display_name': display_name,
                            'memory_count': memory_count,
                            'last_modified': last_modified
                        })
                    except Exception as e:
                        app.logger.warning(f"读取核心记忆文件 {filename} 失败: {e}")
                        continue
        
        # 按修改时间倒序排列
        files.sort(key=lambda x: x['last_modified'], reverse=True)
        
        return jsonify({'status': 'success', 'files': files})
        
    except Exception as e:
        app.logger.error(f"获取核心记忆文件列表失败: {e}")
        return jsonify({'status': 'error', 'message': f'获取失败: {str(e)}'}), 500


def get_core_memory(filename):
    """获取指定核心记忆文件的内容"""
    try:
        # 验证文件名安全性
        if not filename.endswith('_core_memory.json'):
            return jsonify({'status': 'error', 'error': '无效的文件名'}), 400
            
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        file_path = _safe_file_path(core_memory_dir, filename)
        if not file_path:
            return jsonify({'status': 'error', 'error': '无效的文件路径'}), 400
        
        if not os.path.exists(file_path):
            return jsonify({'status': 'error', 'error': '文件不存在'}), 404
        
        # 读取记忆文件
        with open(file_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
        
        # 确保返回的是列表格式
        if not isinstance(memories, list):
            memories = []
        
        # 字段名兼容性处理：处理旧版本的time字段，统一使用timestamp字段
        for memory in memories:
            if isinstance(memory, dict):
                # 如果有旧版本的time字段但没有timestamp字段，则将time转换为timestamp
                if 'time' in memory and 'timestamp' not in memory:
                    memory['timestamp'] = memory['time']
                    del memory['time']  # 删除旧字段，避免冗余
            
        return jsonify({'status': 'success', 'memories': memories})
        
    except Exception as e:
        app.logger.error(f"获取核心记忆文件 {filename} 失败: {e}")
        return jsonify({'status': 'error', 'error': f'读取失败: {str(e)}'}), 500


def save_core_memory(filename):
    """保存核心记忆到指定文件"""
    try:
        # 验证文件名安全性
        if not filename.endswith('_core_memory.json'):
            return jsonify({'status': 'error', 'message': '无效的文件名'}), 400
            
        data = request.json
        memories = data.get('memories', [])
        
        # 验证数据格式
        if not isinstance(memories, list):
            return jsonify({'status': 'error', 'message': '记忆数据必须是数组格式'}), 400
        
        # 验证每个记忆片段的格式
        for i, memory in enumerate(memories):
            if not isinstance(memory, dict):
                return jsonify({'status': 'error', 'message': f'第{i+1}个记忆片段格式错误'}), 400
            
            # 字段名兼容性检查：支持time字段，但统一转换为timestamp
            if 'time' in memory and 'timestamp' not in memory:
                memory['timestamp'] = memory['time']
                del memory['time']  # 删除旧字段，避免冗余
            
            # 验证必要字段
            if 'timestamp' not in memory or 'importance' not in memory or 'summary' not in memory:
                return jsonify({'status': 'error', 'message': f'第{i+1}个记忆片段缺少必要字段(timestamp、importance、summary)'}), 400
                
            if not isinstance(memory['importance'], int) or not (1 <= memory['importance'] <= 10):
                return jsonify({'status': 'error', 'message': f'第{i+1}个记忆片段的重要度必须是1-10的整数'}), 400
        
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        os.makedirs(core_memory_dir, exist_ok=True)
        
        file_path = _safe_file_path(core_memory_dir, filename)
        if not file_path:
            return jsonify({'status': 'error', 'message': '无效的文件路径'}), 400
        
        # 保存记忆文件
        atomic_write_json(file_path, memories, indent=2)
        
        app.logger.info(f"已保存核心记忆文件: {filename}")
        log_audit("save_core_memory", detail=f"保存核心记忆 {filename}")
        return jsonify({'status': 'success', 'message': '核心记忆已保存'})
        
    except Exception as e:
        app.logger.error(f"保存核心记忆文件 {filename} 失败: {e}")
        return jsonify({'status': 'error', 'message': f'保存失败: {str(e)}'}), 500


def delete_core_memory(filename):
    """删除核心记忆文件"""
    try:
        # 验证文件名安全性
        if not filename.endswith('_core_memory.json'):
            return jsonify({'status': 'error', 'message': '无效的文件名'}), 400
            
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        file_path = _safe_file_path(core_memory_dir, filename)
        if not file_path:
            return jsonify({'status': 'error', 'message': '无效的文件路径'}), 400
        
        if not os.path.exists(file_path):
            return jsonify({'status': 'error', 'message': '文件不存在'}), 404
        
        # 删除文件
        os.remove(file_path)
        
        app.logger.info(f"已删除核心记忆文件: {filename}")
        return jsonify({'status': 'success', 'message': '核心记忆文件已删除'})
        
    except Exception as e:
        app.logger.error(f"删除核心记忆文件 {filename} 失败: {e}")
        return jsonify({'status': 'error', 'message': f'删除失败: {str(e)}'}), 500

