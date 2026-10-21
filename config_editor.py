# -*- coding: utf-8 -*-

# ***********************************************************************
# Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot.
# WeChatBot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# WeChatBot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with WeChatBot.  If not, see <http://www.gnu.org/licenses/>.
# ***********************************************************************

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, Response, send_file
import sys
import re
import ast
import os
import subprocess
import psutil
import signal
import openai
import tempfile
import shutil
from filelock import FileLock
from functools import wraps
import webbrowser
from threading import Timer
from flask import Flask
import logging
from queue import Queue, Empty
import time
import json
from werkzeug.utils import secure_filename
import uuid
import base64
import mimetypes
from datetime import datetime
import zipfile
from bot_runtime import (
    trigger_emergency_stop,
    trigger_graceful_stop,
    clear_emergency_stop,
    clear_stop_request,
    emergency_stop_requested,
    read_status_file,
    read_event_logs,
    mask_secrets,
)
from webui_bot_process import (
    bot_creationflags,
    ignore_sigbreak_in_webui,
    inspect_bot_process,
    log_spawn_pids,
    send_ctrl_break_isolated,
    start_bot_preflight,
    status_pid,
    webui_pid,
)
from app_config import (
    load_config as load_structured_config,
    save_config as save_structured_config,
    validate_config as validate_structured_config,
    get_default_config as structured_default_config,
    verify_webui_password,
    LOCAL_CONFIG_PATH,
)
from capabilities import evaluate_capabilities
from audit import log_audit, read_audit
from store_io import atomic_write_json, atomic_write_text, read_json

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FORUM_DATA_DIR = os.path.join(BASE_DIR, 'forum_data')

def hide_api_key(api_key):
    """
    隐藏API Key，只显示前4位和后4位，中间用*替代
    """
    if not api_key or len(api_key) <= 8:
        return api_key  # 太短的key不处理
    
    # 显示前4位和后4位，中间用*替代
    return api_key[:4] + '*' * max(4, len(api_key) - 8) + api_key[-4:]

def is_hidden_api_key(api_key):
    """
    检查API Key是否是隐藏版本
    """
    return api_key and '*' in api_key

def _json_error(error_code, message, detail='', status=400, **extra):
    payload = {
        'ok': False,
        'error': error_code,
        'message': message,
        'detail': detail or message,
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    return jsonify(payload), status

def listen_list_from_form(nicknames, prompt_files, conversation_ids=None, enabled_flags=None):
    """校验并解析监听对象表单。不完整行返回 (None, error_dict)，不再静默跳过。

    成功时返回结构化行列表。兼容旧调用方：每行含 listen_row=[nickname, prompt]。
    """
    nicknames = list(nicknames or [])
    prompt_files = list(prompt_files or [])
    conversation_ids = list(conversation_ids or [])
    enabled_flags = list(enabled_flags or [])
    if len(nicknames) != len(prompt_files):
        return None, {
            'error': 'VALIDATION_ERROR',
            'message': '监听对象名称与 Prompt 数量不一致',
            'detail': f'nickname={len(nicknames)} prompt_file={len(prompt_files)}',
        }
    result = []
    seen_names = {}
    for index, (nick, prompt) in enumerate(zip(nicknames, prompt_files), start=1):
        nick_stripped = (nick or '').strip()
        prompt_stripped = (prompt or '').strip()
        if not nick_stripped:
            return None, {
                'error': 'VALIDATION_ERROR',
                'message': f'第 {index} 个监听对象未填写监听对象名称',
                'detail': f'row={index} field=nickname',
                'row': index,
                'field': 'nickname',
            }
        if not prompt_stripped:
            return None, {
                'error': 'VALIDATION_ERROR',
                'message': f'监听对象「{nick_stripped}」尚未选择 Prompt',
                'detail': f'row={index} field=prompt_file',
                'row': index,
                'field': 'prompt_file',
            }
        if nick_stripped in seen_names:
            return None, {
                'error': 'VALIDATION_ERROR',
                'message': '存在重复监听对象名称。',
                'detail': f'display_name={nick_stripped} row={index}',
                'row': index,
                'field': 'nickname',
            }
        seen_names[nick_stripped] = index
        conv_id = ''
        if index <= len(conversation_ids):
            conv_id = (conversation_ids[index - 1] or '').strip()
        enabled = True
        if index <= len(enabled_flags):
            flag = str(enabled_flags[index - 1] or '').strip().lower()
            enabled = flag not in ('0', 'false', 'off', 'no', '')
        result.append({
            'id': conv_id,
            'display_name': nick_stripped,
            'prompt_name': prompt_stripped,
            'enabled': enabled,
            'listen_row': [nick_stripped, prompt_stripped],
        })
    return result, None


def listen_rows_as_listen_list(rows):
    return [item['listen_row'] if isinstance(item, dict) else item for item in (rows or [])]


def ui_listen_rows(config):
    """监听对象表格行：优先 CONVERSATIONS，否则 LISTEN_LIST。"""
    from conversation_store import conversations_for_ui, prompt_name_of
    cfg = config or {}
    conversations = conversations_for_ui(cfg)
    agents = cfg.get('AGENT_CONFIGS') or []
    rows = []
    for conv in conversations:
        rows.append({
            'id': conv.get('id') or '',
            'display_name': conv.get('display_name') or '',
            'prompt_name': prompt_name_of(conv, agents),
            'enabled': bool(conv.get('enabled', True)),
            'conversation_type': conv.get('conversation_type') or 'UNKNOWN',
        })
    if rows:
        return rows
    for item in cfg.get('LISTEN_LIST') or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            rows.append({
                'id': '',
                'display_name': item[0],
                'prompt_name': item[1],
                'enabled': True,
                'conversation_type': 'UNKNOWN',
            })
    return rows

def safe_type_convert(value, target_type, default_value=None, field_name=""):
    """
    安全的类型转换函数，防止整数转换为字符串
    
    Args:
        value: 要转换的值
        target_type: 目标类型 (int, float, bool)
        default_value: 转换失败时的默认值
        field_name: 字段名，用于日志记录
    
    Returns:
        转换后的值或默认值
    """
    try:
        str_value = str(value).strip()
        
        if target_type == int:
            if str_value and str_value.isdigit():
                return int(str_value)
            elif str_value == '':
                return 0 if default_value is None else default_value
            else:
                if field_name:
                    app.logger.warning(f"配置项 {field_name} 的值 '{value}' 包含非数字字符，使用默认值。")
                return default_value if default_value is not None else 0
                
        elif target_type == float:
            if str_value:
                import re
                if re.match(r'^-?\d+(\.\d+)?$', str_value):
                    return float(str_value)
                else:
                    if field_name:
                        app.logger.warning(f"配置项 {field_name} 的值 '{value}' 不是有效的数字格式，使用默认值。")
                    return default_value if default_value is not None else 0.0
            else:
                return 0.0 if default_value is None else default_value
                
        elif target_type == bool:
            return str_value.lower() in ('on', 'true', '1', 'yes')
            
    except (ValueError, TypeError) as e:
        if field_name:
            app.logger.warning(f"配置项 {field_name} 类型转换失败: {e}，使用默认值。")
        return default_value if default_value is not None else (0 if target_type == int else 0.0 if target_type == float else False)
    
    return value

def validate_config_types(config_path=None):
    """校验结构化配置的类型与范围。"""
    try:
        issues = validate_structured_config(parse_config())
        for item in issues:
            if item.get("code") in ("TYPE", "RANGE"):
                app.logger.warning(item.get("message"))
        return True
    except Exception as e:
        app.logger.warning(f"配置类型校验失败: {e}")
        return False

app.secret_key = load_structured_config().get('FLASK_SECRET_KEY') or os.urandom(24).hex()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=False,
)
bot_process = None

# 全局日志队列
log_queue = Queue()

CHAT_CONTEXTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_contexts.json')
CHAT_CONTEXTS_LOCK_FILE = CHAT_CONTEXTS_FILE + '.lock'

last_heartbeat_time = 0  # 上次收到心跳的时间戳
last_runtime_snapshot = {}
current_bot_pid = None
current_bot_meta = {}
HEARTBEAT_TIMEOUT = 15   # 心跳超时阈值（秒），应大于 bot.py 的 HEARTBEAT_INTERVAL

def get_chat_context_users():
    """从 chat_contexts.json 读取用户列表 (即顶级键)"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return []
    try:
        with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return list(data.keys())
    except (json.JSONDecodeError, IOError) as e:
        app.logger.error(f"读取 chat_contexts.json 失败: {e}")
        return []

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = parse_config()
    if not config.get('ENABLE_LOGIN_PASSWORD', False):
        return redirect(url_for('index'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        if verify_webui_password(password, config):
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="密码错误")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        config = parse_config()
        if config.get('ENABLE_LOGIN_PASSWORD', False):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def _is_path_inside(base_dir, target_path):
    """确认目标文件仍在允许目录内，防止路径穿越。"""
    try:
        base = os.path.normcase(os.path.realpath(base_dir))
        target = os.path.normcase(os.path.realpath(target_path))
        return os.path.commonpath([base, target]) == base
    except (ValueError, OSError):
        return False

def _safe_file_path(base_dir, filename):
    """将用户传入的文件名限制在 base_dir 内。"""
    if not filename or not isinstance(filename, str):
        return None
    if os.path.isabs(filename):
        return None
    normalized = filename.replace('\\', '/').lstrip('/')
    if '..' in normalized.split('/'):
        return None
    candidate = os.path.join(os.path.realpath(base_dir), os.path.basename(normalized))
    if not _is_path_inside(base_dir, candidate):
        return None
    return candidate

@app.route('/start_bot', methods=['POST'])
@login_required
def start_bot():
    global bot_process, last_runtime_snapshot, last_heartbeat_time, current_bot_pid, current_bot_meta
    flask_alive = bot_process is not None and bot_process.poll() is None
    extra_pids = [current_bot_pid]
    if bot_process and bot_process.pid:
        extra_pids.append(bot_process.pid)
    preflight = start_bot_preflight(
        BASE_DIR,
        web_pid=webui_pid(),
        status=read_status_file() or {},
        extra_pids=extra_pids,
        flask_bot_alive=flask_alive,
    )
    if not preflight.get("allow"):
        living_pid = preflight.get("pid")
        if living_pid:
            current_bot_pid = living_pid
        app.logger.warning(
            "拒绝第二次启动 Bot：reason=%s pid=%s WEB_PID=%s",
            preflight.get("reason"),
            living_pid,
            webui_pid(),
        )
        msg = "项目已有存活 Bot，拒绝第二次启动"
        return {
            "status": "already_running",
            "error": msg,
            "message": msg,
            "reason": preflight.get("reason"),
            "pid": living_pid,
            "web_pid": webui_pid(),
        }, 409

    if bot_process is None or bot_process.poll() is not None:
        # 如果目录下存在 user_timers.json 则删除
        user_timers_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_timers.json')
        if os.path.exists(user_timers_path):
            try:
                os.remove(user_timers_path)
            except Exception as e:
                app.logger.warning(f"重置主动消息定时器失败: {e}")

        clear_emergency_stop()
        clear_stop_request()
        last_heartbeat_time = 0
        last_runtime_snapshot = {'state': 'STARTING', 'updated_at': time.time()}

        bot_dir = os.path.dirname(os.path.abspath(__file__))
        
        bot_py = os.path.join(bot_dir, 'bot.py')
        bot_exe = os.path.join(bot_dir, 'bot.exe')
        
        if os.path.exists(bot_py):
            app.logger.info(f"使用当前解释器启动机器人: {sys.executable} {bot_py}")
            cmd = [sys.executable, bot_py]
        elif os.path.exists(bot_exe):
            cmd = [bot_exe]
        else:
            return {'error': 'No bot executable found'}, 404

        creation_flags = bot_creationflags()
        bot_process = subprocess.Popen(
            cmd,
            creationflags=creation_flags
        )
        current_bot_pid = bot_process.pid
        current_bot_meta = log_spawn_pids(app.logger, bot_process.pid, web_pid=webui_pid()) or {}
        log_audit("start_bot", detail="启动机器人")
        # 等待微信初始化（含窗口恢复重试）。状态文件由 Bot 进程写入，不依赖心跳请求。
        deadline = time.time() + 18
        while time.time() < deadline:
            if bot_process.poll() is not None:
                msg = (
                    f'Bot 启动失败，进程已退出 (退出码 {bot_process.returncode})。'
                    '请确认微信客户端已启动并登录，然后查看 Bot 控制台日志。'
                )
                app.logger.error(msg)
                return {'status': 'failed', 'error': msg, 'message': msg}, 500
            status = read_status_file() or {}
            state = str(status.get('state') or '').upper()
            if state in ('RUNNING', 'DEGRADED'):
                break
            if state == 'ERROR':
                # 等进程真正退出，避免前端先显示启动成功
                time.sleep(0.2)
                continue
            time.sleep(0.25)
    return {'status': 'started', 'pid': bot_process.pid if bot_process else current_bot_pid}, 200

@app.route('/stop_bot', methods=['POST'])
@login_required
def stop_bot():
    global bot_process, last_heartbeat_time, current_bot_pid, last_runtime_snapshot
    # 检查状态时，也考虑 status.json pid 是否指向本项目存活 Bot
    is_considered_running = False
    if bot_process and bot_process.poll() is None:
        is_considered_running = True
    if _bot_process_alive():
        is_considered_running = True

    if not is_considered_running:
        app.logger.info("尝试停止机器人，但根据进程对象和心跳判断，机器人似乎已停止。")
        stop_bot_process(pid_to_kill=_preferred_bot_pid(), force_break=False)
        last_runtime_snapshot['state'] = 'STOPPED'
        last_runtime_snapshot['updated_at'] = time.time()
        return {'status': 'stopped', 'state': 'STOPPED', 'web_pid': webui_pid()}, 200

    trigger_graceful_stop(reason='webui_stop')
    last_runtime_snapshot['state'] = 'STOPPING'
    last_runtime_snapshot['updated_at'] = time.time()

    deadline = time.time() + 12
    stopped = False
    while time.time() < deadline:
        status = read_status_file() or {}
        if str(status.get('state') or '').upper() == 'STOPPED':
            stopped = True
            break
        if not _bot_process_alive():
            stopped = True
            break
        time.sleep(0.2)

    if stopped:
        extra_deadline = time.time() + 5
        while time.time() < extra_deadline and _bot_process_alive():
            time.sleep(0.2)

    pids_to_attempt_kill = _candidate_bot_pids()
    need_force = (not stopped) or _bot_process_alive()
    if need_force:
        app.logger.warning(
            "优雅停止后仍需结束 Bot PID(s): %s stopped=%s",
            pids_to_attempt_kill,
            stopped,
        )
        for pid in pids_to_attempt_kill:
            stop_bot_process(pid_to_kill=pid, force_break=not stopped)

    time.sleep(0.3)
    log_audit("stop_bot", detail="停止机器人")
    last_runtime_snapshot['state'] = 'STOPPED'
    last_runtime_snapshot['updated_at'] = time.time()
    return {'status': 'stopped', 'state': 'STOPPED', 'web_pid': webui_pid()}, 200


def _preferred_bot_pid():
    if current_bot_pid:
        return current_bot_pid
    if bot_process:
        return bot_process.pid
    return status_pid(read_status_file() or {})


def _candidate_bot_pids():
    pids = set()
    if current_bot_pid:
        pids.add(current_bot_pid)
    if bot_process and bot_process.pid:
        pids.add(bot_process.pid)
    spid = status_pid(read_status_file() or {})
    if spid:
        pids.add(spid)
    web = webui_pid()
    pids.discard(web)
    pids.discard(0)
    pids.discard(None)
    return pids


def _bot_process_alive():
    """以 status.json pid + cmdline 身份确认，不单凭 bot_process.poll() / pid_exists。"""
    web = webui_pid()
    for pid in _candidate_bot_pids():
        verdict = inspect_bot_process(pid, BASE_DIR, web_pid=web)
        if verdict.get("ok"):
            return True
    return False
    
@app.route('/bot_status')
@app.route('/status')
@login_required
def bot_status():
    return jsonify(_build_bot_status())

def _process_is_alive():
    global bot_process, last_heartbeat_time, current_bot_pid
    process_alive_via_flask_obj = bot_process is not None and bot_process.poll() is None
    heartbeat_is_recent = (time.time() - last_heartbeat_time) < HEARTBEAT_TIMEOUT
    process_alive_via_current_pid = False
    if current_bot_pid is not None:
        try:
            if psutil.pid_exists(current_bot_pid):
                process_alive_via_current_pid = True
        except psutil.Error:
            pass
    if process_alive_via_flask_obj:
        return True
    if heartbeat_is_recent and process_alive_via_current_pid:
        return True
    if heartbeat_is_recent and not process_alive_via_current_pid and current_bot_pid is not None:
        return False
    if heartbeat_is_recent:
        return True
    return False

def _format_uptime(seconds):
    seconds = int(seconds or 0)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"

def _build_bot_status():
    global last_runtime_snapshot
    alive = _process_is_alive()
    file_status = read_status_file()
    snapshot = dict(last_runtime_snapshot or {})
    snapshot.update(file_status or {})
    if emergency_stop_requested() and not alive:
        state = 'STOPPED'
    elif not alive:
        state = snapshot.get('state') if snapshot.get('state') in ('ERROR', 'STOPPED') else 'STOPPED'
    else:
        state = snapshot.get('state') or 'RUNNING'
    if state == 'STOPPED':
        current_status = 'stopped'
    elif state == 'STOPPING':
        current_status = 'stopping'
    elif alive:
        current_status = 'running'
    else:
        current_status = 'stopped'
    try:
        cfg = parse_config()
        listen_count = len(cfg.get('LISTEN_LIST') or [])
        model_name = cfg.get('MODEL') or ''
        key = str(cfg.get('DEEPSEEK_API_KEY') or '').strip()
        api_configured = bool(key) and key not in ('YOUR_API_KEY', 'YOUR_API_KEY_HERE', 'YOUR_PASSWORD')
    except Exception:
        cfg = {}
        listen_count = 0
        model_name = ''
        api_configured = False
    ai_status = snapshot.get('ai') or ('ok' if api_configured else 'error')
    wechat_status = snapshot.get('wechat') or ('connected' if alive else 'disconnected')
    return {
        'status': current_status,
        'state': state,
        'alive': alive,
        'emergency': bool(snapshot.get('emergency') or emergency_stop_requested()),
        'wechat': wechat_status,
        'ai': ai_status,
        'ai_detail': snapshot.get('ai_detail') or ('已配置' if api_configured else '未配置'),
        'model': model_name,
        'listen_count': listen_count,
        'uptime_seconds': snapshot.get('uptime_seconds') if alive else 0,
        'uptime_text': _format_uptime(snapshot.get('uptime_seconds') if alive else 0),
        'today_received': snapshot.get('today_received') or 0,
        'today_replied': snapshot.get('today_replied') or 0,
        'today_errors': snapshot.get('today_errors') or 0,
        'today_llm_calls': snapshot.get('today_llm_calls') or 0,
        'today_llm_main': snapshot.get('today_llm_main') or 0,
        'today_llm_failed': snapshot.get('today_llm_failed') or 0,
        'send_queue_pending': snapshot.get('send_queue_pending') or 0,
        'degraded_reasons': snapshot.get('degraded_reasons') or [],
        'capabilities': evaluate_capabilities(cfg, snapshot).get('_list') or [],
        'recent_chats': snapshot.get('recent_chats') or [],
        'recent_errors': snapshot.get('recent_errors') or [],
        'recent_llm': snapshot.get('recent_llm') or [],
        'recent_audit': read_audit(limit=20),
        'pid': current_bot_pid,
        'web_pid': webui_pid(),
    }

@app.route('/emergency_stop', methods=['POST'])
@login_required
def emergency_stop():
    """独立于 Bot 消息线程的紧急停止：先写标志文件，再终止进程。"""
    global last_runtime_snapshot
    trigger_emergency_stop(reason='webui_emergency_stop')
    log_audit("emergency_stop", detail="紧急停止")
    last_runtime_snapshot = {
        'state': 'STOPPING',
        'emergency': True,
        'updated_at': time.time(),
    }
    time.sleep(0.2)
    stop_bot()
    last_runtime_snapshot = {
        'state': 'STOPPED',
        'emergency': True,
        'updated_at': time.time(),
    }
    return jsonify({'status': 'emergency_stopped', 'state': 'STOPPED'}), 200

@app.route('/restart_bot', methods=['POST'])
@login_required
def restart_bot():
    stop_bot()
    time.sleep(0.5)
    return start_bot()

@app.route('/api/runtime/overview')
@login_required
def runtime_overview():
    return jsonify(_build_bot_status())

@app.route('/api/runtime/logs')
@login_required
def runtime_event_logs():
    category = request.args.get('category', '').strip()
    limit = request.args.get('limit', 200, type=int)
    return jsonify({'logs': read_event_logs(limit=limit, category=category)})

@app.route('/api/runtime/audit')
@login_required
def runtime_audit_logs():
    limit = request.args.get('limit', 100, type=int)
    return jsonify({'audit': read_audit(limit=limit)})

@app.route('/api/test_ai_connection', methods=['POST'])
@login_required
def test_ai_connection():
    try:
        cfg = parse_config()
        api_key = cfg.get('DEEPSEEK_API_KEY') or ''
        if not api_key or api_key in ('YOUR_API_KEY', 'YOUR_API_KEY_HERE') or '*' in str(api_key):
            return jsonify({'ok': False, 'message': '主模型 API Key 未配置'}), 400
        import openai
        client = openai.OpenAI(api_key=api_key, base_url=cfg.get('DEEPSEEK_BASE_URL'))
        started = time.time()
        client.models.list()
        elapsed = time.time() - started
        return jsonify({
            'ok': True,
            'message': f'连接成功，耗时 {elapsed:.2f}s',
            'model': cfg.get('MODEL') or '',
        })
    except Exception as e:
        return jsonify({'ok': False, 'message': mask_secrets(str(e))}), 400

@app.route('/submit_config', methods=['POST'])
@login_required
def submit_config():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return _json_error(
            'BOT_RUNNING',
            '程序正在运行，请先停止再保存配置',
            'bot_process is alive',
            status=400,
        )
    try:
        if not request.form:
            return _json_error('EMPTY_FORM', '空的表单提交', status=400)
        
        current_config_before_update = parse_config()
        old_listen_list_map = {item[0]: item[1] for item in current_config_before_update.get('LISTEN_LIST', [])}

        new_values_for_config_py = {}
        
        # 处理API Key字段的特殊逻辑
        api_key_fields = ['DEEPSEEK_API_KEY', 'MOONSHOT_API_KEY', 'ONLINE_API_KEY', 'ASSISTANT_API_KEY', 'FORUM_API_KEY']
        for field in api_key_fields:
            if field in request.form:
                submitted_value = request.form[field].strip()
                if is_hidden_api_key(submitted_value):
                    # 如果提交的是隐藏版本，保持原值不变
                    new_values_for_config_py[field] = current_config_before_update.get(field, '')
                else:
                    # 如果提交的是新值，使用新值
                    new_values_for_config_py[field] = submitted_value

        nicknames_from_form = request.form.getlist('nickname')
        prompt_files_from_form = request.form.getlist('prompt_file')
        conversation_ids_from_form = request.form.getlist('conversation_id')
        enabled_from_form = request.form.getlist('listen_enabled')
        processed_listen_rows, listen_error = listen_list_from_form(
            nicknames_from_form,
            prompt_files_from_form,
            conversation_ids_from_form,
            enabled_from_form,
        )
        if listen_error:
            return _json_error(
                listen_error['error'],
                listen_error['message'],
                listen_error.get('detail', ''),
                status=400,
                row=listen_error.get('row'),
                field=listen_error.get('field'),
            )
        from conversation_store import (
            ConversationValidationError,
            apply_listen_rows,
            project_listen_list,
        )
        from agent_store import ensure_agents_for_conversations
        try:
            conversations = apply_listen_rows(current_config_before_update, processed_listen_rows)
        except ConversationValidationError as conv_err:
            return _json_error(
                conv_err.code,
                conv_err.message,
                conv_err.detail,
                status=400,
                **(conv_err.extra or {}),
            )
        agents = ensure_agents_for_conversations(
            conversations,
            current_config_before_update.get('AGENT_CONFIGS') or [],
            prompt_root=BASE_DIR,
        )
        processed_listen_list = project_listen_list(conversations, agents)
        new_values_for_config_py['LISTEN_LIST'] = processed_listen_list
        new_values_for_config_py['CONVERSATIONS'] = conversations
        new_values_for_config_py['AGENT_CONFIGS'] = agents
        
        new_listen_list_map = {item[0]: item[1] for item in processed_listen_list}
        
        users_whose_prompt_changed = []
        for nickname, new_prompt in new_listen_list_map.items():
            if nickname in old_listen_list_map and old_listen_list_map[nickname] != new_prompt:
                users_whose_prompt_changed.append(nickname)

        boolean_fields = [
            'ENABLE_IMAGE_RECOGNITION', 'ENABLE_EMOJI_RECOGNITION',
            'ENABLE_EMOJI_SENDING', 'ENABLE_AUTO_MESSAGE', 'ENABLE_MEMORY',
            'UPLOAD_MEMORY_TO_AI', 'ENABLE_LOGIN_PASSWORD', 'ENABLE_REMINDERS',
            'ALLOW_REMINDERS_IN_QUIET_TIME', 'USE_VOICE_CALL_FOR_REMINDERS',
            'ENABLE_ONLINE_API', 'SEPARATE_ROW_SYMBOLS','ENABLE_SCHEDULED_RESTART',
            'ENABLE_GROUP_AT_REPLY', 'ENABLE_GROUP_KEYWORD_REPLY','GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY', 'REMOVE_PARENTHESES',
            'ENABLE_ASSISTANT_MODEL', 'USE_ASSISTANT_FOR_MEMORY_SUMMARY', 'ENABLE_FORUM_CUSTOM_MODEL',
            'IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE', 'ENABLE_SENSITIVE_CONTENT_CLEARING', 'SAVE_MEMORY_TO_SEPARATE_FILE',
            'ENABLE_TEXT_COMMANDS'
        ]
        for field in boolean_fields:
            new_values_for_config_py[field] = field in request.form

        for key_from_form in request.form:
            if key_from_form in ['nickname', 'prompt_file', 'conversation_id', 'listen_enabled'] or key_from_form in boolean_fields or key_from_form in api_key_fields:
                continue 

            value_from_form = request.form[key_from_form].strip()
            
            if key_from_form == 'GROUP_KEYWORD_LIST':
                if value_from_form:
                    normalized_value = re.sub(r'，|\s+', ',', value_from_form)
                    keywords_list = [kw.strip() for kw in normalized_value.split(',') if kw.strip()]
                    new_values_for_config_py[key_from_form] = keywords_list
                else:
                    new_values_for_config_py[key_from_form] = []
                continue

            if key_from_form in current_config_before_update:
                original_type_source = current_config_before_update[key_from_form]
                if isinstance(original_type_source, bool):
                    new_values_for_config_py[key_from_form] = (value_from_form.lower() == 'true')
                elif key_from_form in ["MIN_COUNTDOWN_HOURS", "MAX_COUNTDOWN_HOURS", "AVERAGE_TYPING_SPEED", "RANDOM_TYPING_SPEED_MIN", "RANDOM_TYPING_SPEED_MAX", "TEMPERATURE", "MOONSHOT_TEMPERATURE", "ONLINE_API_TEMPERATURE", "ASSISTANT_TEMPERATURE", "RESTART_INTERVAL_HOURS", "FORUM_TEMPERATURE"]: 
                    try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value:
                            # 验证是否为有效的数字格式
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                # 如果不是有效数字格式，保留原值
                                new_values_for_config_py[key_from_form] = original_type_source
                                app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values_for_config_py[key_from_form] = 0.0
                    except (ValueError, TypeError) as e: 
                        new_values_for_config_py[key_from_form] = original_type_source 
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, int) or key_from_form in ["GROUP_CHAT_RESPONSE_PROBABILITY", "RESTART_INACTIVITY_MINUTES", "ASSISTANT_MAX_TOKEN", "FORUM_MAX_TOKEN"]:
                    try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 0
                        else:
                            # 如果包含非数字字符，保留原值
                            new_values_for_config_py[key_from_form] = original_type_source
                            app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已保留旧值。")
                    except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, float):
                     try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value:
                            # 验证是否为有效的数字格式
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                # 如果不是有效数字格式，保留原值
                                new_values_for_config_py[key_from_form] = original_type_source
                                app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values_for_config_py[key_from_form] = 0.0
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, list):
                    try:
                        evaluated_list = ast.literal_eval(value_from_form)
                        if isinstance(evaluated_list, list):
                            new_values_for_config_py[key_from_form] = evaluated_list
                        else:
                            new_values_for_config_py[key_from_form] = original_type_source
                            app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 解析后不是列表，已保留旧值。")
                    except:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法解析为列表，已保留旧值。")
                else: 
                    new_values_for_config_py[key_from_form] = value_from_form
            else: 
                if key_from_form == "GROUP_CHAT_RESPONSE_PROBABILITY":
                    try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 0
                        else:
                            new_values_for_config_py[key_from_form] = 100
                            app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已设为默认值100。")
                    except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 100
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已设为默认值100。错误: {e}")
                elif key_from_form == "RESTART_INACTIVITY_MINUTES":
                     try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 15
                        else:
                            new_values_for_config_py[key_from_form] = 15
                            app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已设为默认值15。")
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 15 
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已设为默认值15。错误: {e}")

                elif key_from_form == "RESTART_INTERVAL_HOURS":
                     try:
                        str_value = str(value_from_form).strip()
                        if str_value:
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                new_values_for_config_py[key_from_form] = 2.0
                                app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已设为默认值2.0。")
                        else:
                            new_values_for_config_py[key_from_form] = 2.0
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 2.0
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已设为默认值2.0。错误: {e}")
                else:
                    new_values_for_config_py[key_from_form] = value_from_form
        
        update_config(new_values_for_config_py)
        validate_config_types()

        if users_whose_prompt_changed:
            with FileLock(CHAT_CONTEXTS_LOCK_FILE):
                try:
                    if os.path.exists(CHAT_CONTEXTS_FILE):
                        with open(CHAT_CONTEXTS_FILE, 'r+', encoding='utf-8') as f:
                            chat_data = json.load(f)
                            modified_chat_data = False
                            for user_to_clear in users_whose_prompt_changed:
                                if user_to_clear in chat_data:
                                    del chat_data[user_to_clear]
                                    modified_chat_data = True
                                    app.logger.info(f"因Prompt文件变更，用户 '{user_to_clear}' 的聊天上下文已清除。")
                            if modified_chat_data:
                                f.seek(0)
                                json.dump(chat_data, f, ensure_ascii=False, indent=4)
                                f.truncate()
                except (json.JSONDecodeError, IOError) as e:
                    app.logger.error(f"清除因Prompt变更导致的聊天上下文时出错: {e}")
                    
        log_audit("save_config", detail=f"已保存配置，监听对象 {len(processed_listen_list)} 个")
        return jsonify({'ok': True, 'message': '配置保存成功'}), 200
    except Exception as e:
        app.logger.error(f"配置保存失败: {str(e)}")
        return _json_error(
            'CONFIG_WRITE_FAILED',
            '无法写入配置文件',
            str(e),
            status=500,
        )

def stop_bot_process(pid_to_kill=None, force_break=True):
    global bot_process, last_heartbeat_time, current_bot_pid, current_bot_meta
    
    process_killed_successfully = False
    web_pid = webui_pid()

    if pid_to_kill:
        verdict = inspect_bot_process(
            pid_to_kill,
            BASE_DIR,
            web_pid=web_pid,
            expected_create_time=(current_bot_meta or {}).get("create_time"),
        )
        if not verdict.get("ok"):
            app.logger.warning(
                "拒绝停止 PID %s：%s。WEB_PID=%s 保持不变。",
                pid_to_kill,
                verdict.get("reason"),
                web_pid,
            )
            if verdict.get("reason") in ("pid_not_running", "empty_pid", "invalid_pid", "non_positive_pid"):
                process_killed_successfully = True
            else:
                last_heartbeat_time = 0
                return
        else:
            try:
                bot_psutil = psutil.Process(pid_to_kill)
                app.logger.info(
                    "尝试终止机器人进程 PID=%s WEB_PID=%s cmdline=%s",
                    pid_to_kill,
                    web_pid,
                    (verdict.get("info") or {}).get("cmdline_text"),
                )
                sent_break = False
                if force_break and os.name == "nt":
                    try:
                        sent_break = send_ctrl_break_isolated(pid_to_kill)
                        if sent_break:
                            app.logger.info(
                                "已向 Bot process group PID %s 发送 CTRL_BREAK（WebUI PID %s 不在目标组）。",
                                pid_to_kill,
                                web_pid,
                            )
                    except Exception as break_err:
                        app.logger.warning(f"发送 CTRL_BREAK 失败，将直接结束进程: {break_err}")
                try:
                    bot_psutil.wait(timeout=8 if sent_break else 2)
                    app.logger.info(f"PID {pid_to_kill} 已自行退出。")
                    process_killed_successfully = True
                except psutil.TimeoutExpired:
                    app.logger.warning(f"等待 PID {pid_to_kill} 退出超时，尝试 terminate。")
                    bot_psutil.terminate()
                    bot_psutil.wait(timeout=5)
                    app.logger.info(f"通过 terminate 成功停止了PID {pid_to_kill}。")
                    process_killed_successfully = True
            except psutil.NoSuchProcess:
                app.logger.info(f"尝试终止PID {pid_to_kill} 时，进程已不存在。")
                process_killed_successfully = True
            except psutil.TimeoutExpired:
                app.logger.warning(f"Terminate PID {pid_to_kill} 超时，尝试 kill。")
                try:
                    if psutil.pid_exists(pid_to_kill):
                        still = inspect_bot_process(pid_to_kill, BASE_DIR, web_pid=web_pid)
                        if not still.get("ok"):
                            app.logger.warning(
                                "kill 前再次校验失败 PID %s：%s，放弃。",
                                pid_to_kill,
                                still.get("reason"),
                            )
                        else:
                            bot_psutil_kill = psutil.Process(pid_to_kill)
                            bot_psutil_kill.kill()
                            bot_psutil_kill.wait(timeout=3)
                            app.logger.info(f"通过 kill 成功停止了PID {pid_to_kill}。")
                            process_killed_successfully = True
                except psutil.NoSuchProcess:
                    app.logger.info(f"尝试 kill PID {pid_to_kill} 时，进程已不存在。")
                    process_killed_successfully = True
                except Exception as e_kill:
                    app.logger.error(f"Kill PID {pid_to_kill} 失败: {e_kill}")
            except Exception as e:
                app.logger.error(f"停止PID {pid_to_kill} 时发生错误: {e}")

    # 如果被杀死的PID是Flask自己启动的进程，则清空bot_process
    if bot_process and pid_to_kill == bot_process.pid and process_killed_successfully:
        app.logger.info(f"清空 Flask 维护的 bot_process 对象 (原PID: {bot_process.pid})。")
        bot_process = None
    
    # 如果被杀死的PID是当前记录的机器人PID，则清空current_bot_pid
    if current_bot_pid and pid_to_kill == current_bot_pid and process_killed_successfully:
        app.logger.info(f"清空 current_bot_pid (原PID: {current_bot_pid})。")
        current_bot_pid = None
        current_bot_meta = {}

    last_heartbeat_time = 0
    if not current_bot_pid and not bot_process: # 确保如果所有已知进程句柄都清了，才彻底标记
        app.logger.info("所有已知的机器人进程句柄均已清理。重置心跳时间。")
    elif current_bot_pid:
        app.logger.warning(f"调用 stop_bot_process 后，current_bot_pid ({current_bot_pid}) 仍有值。可能存在未完全停止的实例或状态不同步。但心跳已重置。")

@app.route('/bot_heartbeat', methods=['POST'])
def bot_heartbeat():
    global last_heartbeat_time, current_bot_pid, last_runtime_snapshot, current_bot_meta
    try:
        last_heartbeat_time = time.time()
        data = request.get_json()
        
        if data and 'pid' in data:
            received_pid = data.get('pid')
            if received_pid and isinstance(received_pid, int):
                verdict = inspect_bot_process(received_pid, BASE_DIR, web_pid=webui_pid())
                if not verdict.get("ok"):
                    app.logger.warning(
                        "Ignored heartbeat PID %s: %s (WEB_PID=%s)",
                        received_pid,
                        verdict.get("reason"),
                        webui_pid(),
                    )
                else:
                    info = verdict.get("info") or {}
                    if current_bot_pid != received_pid:
                        app.logger.info(f"Bot PID updated via heartbeat: old={current_bot_pid}, new={received_pid}")
                        current_bot_pid = received_pid
                    current_bot_meta = {
                        "WEB_PID": webui_pid(),
                        "BOT_PID": received_pid,
                        "BOT_PPID": info.get("ppid"),
                        "create_time": info.get("create_time"),
                        "cmdline": info.get("cmdline_text"),
                    }
            else:
                app.logger.warning(f"Received heartbeat with invalid PID: {received_pid}")
        if data and isinstance(data.get('runtime'), dict):
            last_runtime_snapshot = data['runtime']

        return jsonify({'status': 'heartbeat_received'}), 200
    except Exception as e:
        app.logger.error(f"Error processing heartbeat: {e}")
        current_bot_pid = None
        return jsonify({'error': 'Failed to process heartbeat'}), 500

def parse_config():
    return load_structured_config()

def update_config(new_values):
    """写入 config.local.json + .env，不再正则改 Python 源码。"""
    save_structured_config(new_values or {})

@app.route('/quick_start', methods=['GET', 'POST'])
@login_required
def quick_start():
    if request.method == 'POST':
        try:
            config = parse_config()
            new_values = {}

            api_provider = request.form.get('quick_start_api_provider', 'weapis')
            api_key_raw = request.form.get('quick_start_api_key', '').strip()
            
            # 处理API Key，如果是隐藏版本则保持原值
            if is_hidden_api_key(api_key_raw):
                api_key = config.get('DEEPSEEK_API_KEY', '')
            else:
                api_key = api_key_raw

            keys_to_clear_for_non_weapis = [
                'MOONSHOT_API_KEY', 'ONLINE_API_KEY',
                'MOONSHOT_BASE_URL', 'ONLINE_BASE_URL',
                'MOONSHOT_MODEL', 'ONLINE_MODEL'
            ]

            if api_provider == 'weapis':
                if api_key:
                    new_values['DEEPSEEK_API_KEY'] = api_key
                    new_values['MOONSHOT_API_KEY'] = api_key
                    new_values['ONLINE_API_KEY'] = api_key
                new_values['DEEPSEEK_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['MOONSHOT_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['ONLINE_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['MOONSHOT_MODEL'] = 'gpt-4o'
                new_values['ONLINE_MODEL'] = 'net-gpt-4o-mini'
                if not config.get('MODEL','').strip():
                    new_values['MODEL'] = 'deepseek-ai/DeepSeek-V3'
                new_values['ENABLE_ONLINE_API'] = 'ENABLE_ONLINE_API' in request.form
            
            else:
                if api_provider == 'siliconflow':
                    new_values['DEEPSEEK_BASE_URL'] = 'https://api.siliconflow.cn/v1/'
                elif api_provider == 'deepseek_official':
                    new_values['DEEPSEEK_BASE_URL'] = 'https://api.deepseek.com'
                elif api_provider == 'other':
                    custom_base_url = request.form.get('quick_start_custom_base_url', '').strip()
                    if custom_base_url:
                        new_values['DEEPSEEK_BASE_URL'] = custom_base_url
                    else:
                        new_values['DEEPSEEK_BASE_URL'] = ""
                
                if api_key:
                    new_values['DEEPSEEK_API_KEY'] = api_key
                
                for key_to_clear in keys_to_clear_for_non_weapis:
                    new_values[key_to_clear] = "" 
                new_values['ENABLE_ONLINE_API'] = False

            nicknames = request.form.getlist('nickname')
            prompt_files_form = request.form.getlist('prompt_file')
            conversation_ids_form = request.form.getlist('conversation_id')
            enabled_form = request.form.getlist('listen_enabled')
            listen_rows, listen_error = listen_list_from_form(
                nicknames, prompt_files_form, conversation_ids_form, enabled_form,
            )
            if listen_error:
                return _json_error(
                    listen_error['error'],
                    listen_error['message'],
                    listen_error.get('detail', ''),
                    status=400,
                    row=listen_error.get('row'),
                    field=listen_error.get('field'),
                )
            from conversation_store import apply_listen_rows, project_listen_list, ConversationValidationError
            from agent_store import ensure_agents_for_conversations
            try:
                conversations = apply_listen_rows(config, listen_rows)
            except ConversationValidationError as conv_err:
                return _json_error(conv_err.code, conv_err.message, conv_err.detail, status=400)
            agents = ensure_agents_for_conversations(
                conversations, config.get('AGENT_CONFIGS') or [], prompt_root=BASE_DIR,
            )
            listen_list = project_listen_list(conversations, agents)
            new_values['LISTEN_LIST'] = listen_list
            new_values['CONVERSATIONS'] = conversations
            new_values['AGENT_CONFIGS'] = agents
            new_values['ENABLE_AUTO_MESSAGE'] = 'ENABLE_AUTO_MESSAGE' in request.form
            
            update_config(new_values)
            return redirect(url_for('index'))
        except Exception as e:
            app.logger.error(f"快速配置保存错误: {e}")
            return redirect(url_for('quick_start'))

    try:
        config = parse_config()
        prompt_files_list = list_prompt_names()
        
        current_api_provider = 'weapis'
        current_custom_base_url = ''
        
        deepseek_url = config.get('DEEPSEEK_BASE_URL', '')
        
        is_weapis_setup = (
            deepseek_url == 'https://vg.v1api.cc/v1' and
            config.get('MOONSHOT_BASE_URL') == 'https://vg.v1api.cc/v1' and
            config.get('ONLINE_BASE_URL') == 'https://vg.v1api.cc/v1'
        )

        if is_weapis_setup:
            current_api_provider = 'weapis'
        elif deepseek_url == 'https://api.siliconflow.cn/v1/':
            current_api_provider = 'siliconflow'
        elif deepseek_url == 'https://api.deepseek.com':
            current_api_provider = 'deepseek_official'
        elif deepseek_url and deepseek_url != 'https://vg.v1api.cc/v1': 
            current_api_provider = 'other'
            current_custom_base_url = deepseek_url

        # 为快速配置页面也隐藏API Key
        display_config = config.copy()
        api_key_fields = ['DEEPSEEK_API_KEY']
        for field in api_key_fields:
            if field in display_config:
                display_config[field] = hide_api_key(display_config[field])

        return render_template('quick_start.html',
                               config=display_config,
                               prompt_files=prompt_files_list,
                               current_api_provider=current_api_provider,
                               current_custom_base_url=current_custom_base_url)
    except Exception as e:
        app.logger.error(f"加载快速配置页面错误: {e}")
        return "加载快速配置页面错误，请检查日志。"

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    # 在处理 POST 或渲染模板之前检查 API KEY
    current_config_check = parse_config()
    # 检查是否从 quick_start 页面明确跳过
    was_skipped = request.args.get('skipped') == 'true'

    if not current_config_check.get('DEEPSEEK_API_KEY', '').strip():
        # 只有当不是明确跳过，并且是GET请求时，才重定向到 quick_start
        if request.method == 'GET' and not was_skipped:
             return redirect(url_for('quick_start'))

    if request.method == 'POST':
        try:
            config = parse_config()
            new_values = {}

             # 处理二维数组的LISTEN_LIST
            nicknames = request.form.getlist('nickname')
            prompt_files = request.form.getlist('prompt_file')
            conversation_ids = request.form.getlist('conversation_id')
            enabled_flags = request.form.getlist('listen_enabled')
            listen_rows, listen_error = listen_list_from_form(
                nicknames, prompt_files, conversation_ids, enabled_flags,
            )
            if listen_error:
                return _json_error(
                    listen_error['error'],
                    listen_error['message'],
                    listen_error.get('detail', ''),
                    status=400,
                    row=listen_error.get('row'),
                    field=listen_error.get('field'),
                )
            from conversation_store import apply_listen_rows, project_listen_list, ConversationValidationError
            from agent_store import ensure_agents_for_conversations
            try:
                conversations = apply_listen_rows(config, listen_rows)
            except ConversationValidationError as conv_err:
                return _json_error(conv_err.code, conv_err.message, conv_err.detail, status=400)
            agents = ensure_agents_for_conversations(
                conversations, config.get('AGENT_CONFIGS') or [], prompt_root=BASE_DIR,
            )
            listen_list = project_listen_list(conversations, agents)
            new_values['LISTEN_LIST'] = listen_list
            new_values['CONVERSATIONS'] = conversations
            new_values['AGENT_CONFIGS'] = agents

            # 处理其他字段
            submitted_fields = set(request.form.keys()) - {'listen_list'} # listen_list 已处理
            # 修正: submitted_fields应为 {'nickname', 'prompt_file'}
            submitted_fields = set(request.form.keys()) - {'nickname', 'prompt_file'}

            for var in submitted_fields:
                if var not in config and not var.startswith('temp_'): # 忽略不存在于config中的字段, 但保留temp_字段
                    # 如果是 quick_start_api_key 这样的临时字段，则忽略
                    if var == 'quick_start_api_key':
                        continue
                    # 对于其他未知字段，可以打印警告或跳过
                    app.logger.warning(f"表单中存在未知配置项: {var}, 已忽略。")
                    continue
                
                original_value = config.get(var) # 获取原始值及其类型
                value_from_form = request.form[var].strip()

                if var.startswith('temp_'): # 处理 temp_ 前缀的字段，它们决定最终字段的值
                    final_field_name = var.replace('temp_', '')
                    if final_field_name in config: # 确保最终字段名在配置中存在
                        # 这部分逻辑通常在前端JS处理好，后端直接取最终字段
                        # 但为保险起见，这里也处理下
                        # 假设最终字段已由JS写入隐藏input，如 DEEPSEEK_BASE_URL
                        # 这里仅作示例，实际应依赖js将正确的值填入如DEEPSEEK_BASE_URL的name中
                        pass # 依赖js，后端直接用 DEEPSEEK_BASE_URL 等
                    continue # temp_ 字段本身不直接写入配置

                # 类型转换逻辑
                if isinstance(original_value, bool):
                    new_values[var] = value_from_form.lower() in ('on', 'true', '1', 'yes')
                elif isinstance(original_value, int):
                    try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values[var] = int(str_value)
                        elif str_value == '':
                            new_values[var] = 0
                        else:
                            new_values[var] = original_value
                            app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 包含非数字字符，已保留旧值。")
                    except (ValueError, TypeError) as e:
                        new_values[var] = original_value # 保留旧值
                        app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 无法转换为整数，已保留旧值。错误: {e}")
                elif isinstance(original_value, float):
                    try:
                        str_value = str(value_from_form).strip()
                        if str_value:
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values[var] = float(str_value)
                            else:
                                new_values[var] = original_value
                                app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values[var] = 0.0
                    except (ValueError, TypeError) as e:
                        new_values[var] = original_value # 保留旧值
                        app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")

                elif original_value is None and value_from_form: # 如果原配置中某项不存在 (None), 但表单提交了值
                     # 尝试推断类型或默认为字符串
                    try:
                        new_values[var] = ast.literal_eval(value_from_form)
                    except:
                        new_values[var] = value_from_form
                else: # 默认为字符串
                    new_values[var] = value_from_form
            
            # 再次检查布尔字段，确保未勾选时为 False
            boolean_fields_from_editor = [
                'ENABLE_IMAGE_RECOGNITION', 'ENABLE_EMOJI_RECOGNITION',
                'ENABLE_EMOJI_SENDING', 'ENABLE_AUTO_MESSAGE', 'ENABLE_MEMORY',
                'UPLOAD_MEMORY_TO_AI', 'ENABLE_LOGIN_PASSWORD', 'ENABLE_REMINDERS',
                'ALLOW_REMINDERS_IN_QUIET_TIME', 'USE_VOICE_CALL_FOR_REMINDERS',
                'ENABLE_ONLINE_API', 'SEPARATE_ROW_SYMBOLS','ENABLE_SCHEDULED_RESTART',
                'ENABLE_GROUP_AT_REPLY', 'ENABLE_GROUP_KEYWORD_REPLY','GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY','REMOVE_PARENTHESES',
                'ENABLE_ASSISTANT_MODEL', 'USE_ASSISTANT_FOR_MEMORY_SUMMARY',
                'IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE', 'ENABLE_SENSITIVE_CONTENT_CLEARING', 'SAVE_MEMORY_TO_SEPARATE_FILE'
            ]
            for field in boolean_fields_from_editor:
                 # 确保这些字段在表单中存在才处理，否则它们可能来自 quick_start
                if field in request.form or field not in new_values: # 如果在表单中，或尚未设置
                    new_values[field] = field in request.form # 统一处理，在表单中出现即为True

            update_config(new_values)
            validate_config_types()
            
            return redirect(url_for('index')) # 保存后重定向到自身以刷新GET请求
        except Exception as e:
            app.logger.error(f"主配置页保存配置错误: {e}")
            # 渲染错误信息，或重定向到GET并带上错误提示
            return f"保存配置失败: {str(e)}"

    # GET 请求
    try:
        prompt_files = list_prompt_names()
        config = parse_config() # 重新解析以获取最新配置
        chat_context_users = get_chat_context_users()

        # 创建一个隐藏API Key的配置副本用于显示
        display_config = config.copy()
        api_key_fields = ['DEEPSEEK_API_KEY', 'MOONSHOT_API_KEY', 'ONLINE_API_KEY', 'ASSISTANT_API_KEY', 'FORUM_API_KEY']
        for field in api_key_fields:
            if field in display_config:
                display_config[field] = hide_api_key(display_config[field])
        display_config['LOGIN_PASSWORD'] = ''
        display_config['WEBUI_PASSWORD_HASH'] = ''
        display_config['FLASK_SECRET_KEY'] = ''

        return render_template('config_editor.html',
                             config=display_config,
                             prompt_files=prompt_files,
                             chat_context_users=chat_context_users,
                             listen_rows=ui_listen_rows(config))
    except Exception as e:
        app.logger.error(f"加载主配置页面错误: {e}")
        return "加载配置页面错误，请检查日志。"
@app.route('/get_all_reminders')
@login_required
def get_all_reminders():
    """
    获取 JSON 文件中所有的提醒记录 (包括 recurring 和 one-off)。
    """
    try:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recurring_reminders.json')
        if not os.path.exists(json_path):
            return jsonify([]) # 文件不存在则返回空列表

        with open(json_path, 'r', encoding='utf-8') as f:
            all_reminders = json.load(f)

        # 基本验证，确保返回的是列表
        if not isinstance(all_reminders, list):
             app.logger.warning(f"文件 {json_path} 内容不是有效的JSON列表，将返回空列表。")
             return jsonify([])

        return jsonify(all_reminders) # <--- 返回所有提醒

    except json.JSONDecodeError:
        app.logger.error(f"文件 recurring_reminders.json 格式错误，无法解析。")
        return jsonify([]) # 格式错误也返回空列表
    except Exception as e:
        app.logger.error(f"获取所有提醒失败: {str(e)}")
        return jsonify({'error': f'获取所有提醒失败: {str(e)}'}), 500

# 重命名: 保存所有提醒 (覆盖整个文件)
@app.route('/save_all_reminders', methods=['POST']) # <--- Route Renamed
@login_required
def save_all_reminders():
    """
    接收前端提交的所有提醒列表 (recurring 和 one-off)，
    验证后覆盖写入 recurring_reminders.json 文件。
    """
    try:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recurring_reminders.json')
        # 获取前端提交的完整提醒列表
        reminders_data = request.get_json()

        # --- 验证前端提交的数据 ---
        if not isinstance(reminders_data, list):
            raise ValueError("无效的数据格式，应为提醒列表")

        validated_reminders = []
        # 定义验证规则
        recurring_required = ['reminder_type', 'user_id', 'time_str', 'content']
        one_off_required = ['reminder_type', 'user_id', 'target_datetime_str', 'content']
        time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$') # HH:MM
        # YYYY-MM-DD HH:MM (允许个位数月/日，但通常前端datetime-local会补零)
        datetime_pattern = re.compile(r'^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01]) ([01]\d|2[0-3]):([0-5]\d)$')

        for idx, item in enumerate(reminders_data, 1):
            if not isinstance(item, dict):
                 raise ValueError(f"第{idx}条记录不是有效的对象")

            reminder_type = item.get('reminder_type')
            user_id = str(item.get('user_id', '')).strip()
            content = str(item.get('content', '')).strip()

            # 通用验证
            if not reminder_type in ['recurring', 'one-off']:
                 raise ValueError(f"第{idx}条记录类型无效: {reminder_type}")
            if not user_id: raise ValueError(f"第{idx}条用户ID不能为空")
            if len(user_id) > 50: raise ValueError(f"第{idx}条用户ID过长（最大50字符）")
            if not content: raise ValueError(f"第{idx}条内容不能为空")
            if len(content) > 200: raise ValueError(f"第{idx}条内容过长（最大200字符）")

            # 特定类型验证
            if reminder_type == 'recurring':
                if not all(field in item for field in recurring_required):
                    raise ValueError(f"第{idx}条(recurring)记录字段缺失")
                time_str = str(item.get('time_str', '')).strip()
                if not time_pattern.match(time_str):
                    raise ValueError(f"第{idx}条(recurring)时间格式错误，应为 HH:MM ({time_str})")
                validated_reminders.append({
                    'reminder_type': 'recurring',
                    'user_id': user_id,
                    'time_str': time_str,
                    'content': content
                })
            elif reminder_type == 'one-off':
                if not all(field in item for field in one_off_required):
                     raise ValueError(f"第{idx}条(one-off)记录字段缺失")
                target_datetime_str = str(item.get('target_datetime_str', '')).strip()
                # 验证 YYYY-MM-DD HH:MM 格式
                if not datetime_pattern.match(target_datetime_str):
                    raise ValueError(f"第{idx}条(one-off)日期时间格式错误，应为 YYYY-MM-DD HH:MM ({target_datetime_str})")
                validated_reminders.append({
                    'reminder_type': 'one-off',
                    'user_id': user_id,
                    'target_datetime_str': target_datetime_str,
                    'content': content
                })

        # --- 原子化写入操作 ---
        # 使用临时文件确保写入安全，覆盖原文件
        temp_dir = os.path.dirname(json_path)
        with tempfile.NamedTemporaryFile('w', delete=False, dir=temp_dir, encoding='utf-8', suffix='.tmp') as temp_f:
            json.dump(validated_reminders, temp_f, ensure_ascii=False, indent=2) # 写入验证后的完整列表
            temp_path = temp_f.name
        # 替换原文件
        shutil.move(temp_path, json_path)

        return jsonify({'status': 'success', 'message': '所有提醒已更新'})

    except ValueError as ve: # 捕获验证错误
         app.logger.error(f'提醒保存验证失败: {str(ve)}')
         return jsonify({'error': f'数据验证失败: {str(ve)}'}), 400
    except Exception as e:
        app.logger.error(f'提醒保存失败: {str(e)}')
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

@app.route('/import_config', methods=['POST'])
@login_required
def import_config():
    global bot_process
    # 如果 bot 正在运行，则不允许导入配置
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再导入配置'}), 400

    try:
        if 'config_file' not in request.files:
            return jsonify({'error': '未找到上传的配置文件'}), 400
            
        config_file = request.files['config_file']
        if not config_file.filename.endswith('.py'):
            return jsonify({'error': '请上传.py格式的配置文件'}), 400
            
        # 创建临时文件用于解析配置
        with tempfile.NamedTemporaryFile('wb', suffix='.py', delete=False) as temp_f:
            temp_path = temp_f.name
            config_file.save(temp_path)
        
        # 解析临时配置文件
        imported_config = {}
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
                    if match:
                        var_name = match.group(1)
                        var_value_str = match.group(2)
                        try:
                            var_value = ast.literal_eval(var_value_str)
                            imported_config[var_name] = var_value
                        except:
                            imported_config[var_name] = var_value_str
        finally:
            # 清理临时文件
            try:
                os.unlink(temp_path)
            except:
                pass
        
        # 获取当前配置作为基础
        current_config = parse_config()
        
        # 合并配置：只更新导入配置中存在的项
        for key, value in imported_config.items():
            if key in current_config:  # 只更新当前配置中已存在的项
                current_config[key] = value
        
        # 更新配置文件
        update_config(current_config)
        
        return jsonify({'success': True, 'message': '配置导入成功，共导入了{}个有效参数'.format(len(imported_config))}), 200
    except Exception as e:
        app.logger.error(f"配置导入失败: {str(e)}")
        return jsonify({'error': f'导入失败: {str(e)}'}), 500

def create_backup_directory():
    """创建备份目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BASE_DIR, "数据备份", f"{timestamp}_导入备份")
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def backup_existing_data(backup_dir):
    """备份现有数据到指定目录"""
    backed_up_items = []
    
    try:
        # 备份 prompts 文件夹
        prompts_dir = os.path.join(BASE_DIR, 'prompts')
        if os.path.exists(prompts_dir):
            backup_prompts = os.path.join(backup_dir, 'prompts')
            shutil.copytree(prompts_dir, backup_prompts)
            backed_up_items.append('prompts文件夹')
        
        # 备份 emojis 文件夹
        emojis_dir = os.path.join(BASE_DIR, 'emojis')
        if os.path.exists(emojis_dir):
            backup_emojis = os.path.join(backup_dir, 'emojis')
            shutil.copytree(emojis_dir, backup_emojis)
            backed_up_items.append('emojis文件夹')
        
        # 备份 forum_data 文件夹
        forum_data_dir = FORUM_DATA_DIR
        if os.path.exists(forum_data_dir):
            backup_forum = os.path.join(backup_dir, 'forum_data')
            shutil.copytree(forum_data_dir, backup_forum)
            backed_up_items.append('forum_data文件夹')
        
        # 备份 CoreMemory 文件夹
        config = parse_config()
        core_memory_dir = os.path.join(BASE_DIR, config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        if os.path.exists(core_memory_dir):
            backup_core = os.path.join(backup_dir, os.path.basename(core_memory_dir))
            shutil.copytree(core_memory_dir, backup_core)
            backed_up_items.append('CoreMemory文件夹')
        
        # 备份 recurring_reminders.json 文件
        reminders_file = os.path.join(BASE_DIR, 'recurring_reminders.json')
        if os.path.exists(reminders_file):
            backup_reminders = os.path.join(backup_dir, 'recurring_reminders.json')
            shutil.copy2(reminders_file, backup_reminders)
            backed_up_items.append('recurring_reminders.json文件')
        
        # 备份 chat_contexts.json 文件
        chat_contexts_file = os.path.join(BASE_DIR, 'chat_contexts.json')
        if os.path.exists(chat_contexts_file):
            backup_chat_contexts = os.path.join(backup_dir, 'chat_contexts.json')
            shutil.copy2(chat_contexts_file, backup_chat_contexts)
            backed_up_items.append('chat_contexts.json文件')
        
        # 备份 Memory_Temp 文件夹
        config = parse_config()
        memory_temp_dirname = config.get('MEMORY_TEMP_DIR', 'Memory_Temp')
        memory_temp_dir = os.path.join(BASE_DIR, memory_temp_dirname)
        if os.path.exists(memory_temp_dir):
            backup_memory_temp = os.path.join(backup_dir, memory_temp_dirname)
            shutil.copytree(memory_temp_dir, backup_memory_temp)
            backed_up_items.append('Memory_Temp文件夹')
        
        # 备份 config.py 文件
        config_file = os.path.join(BASE_DIR, 'config.py')
        if os.path.exists(config_file):
            backup_config = os.path.join(backup_dir, 'config.py')
            shutil.copy2(config_file, backup_config)
            backed_up_items.append('config.py文件')
        
        return backed_up_items
    except Exception as e:
        app.logger.error(f"备份数据失败: {str(e)}")
        raise Exception(f"备份失败: {str(e)}")

def import_directory_data(source_dir):
    """从源目录导入数据"""
    imported_items = []
    
    try:
        # 导入 config.py 文件
        source_config = os.path.join(source_dir, 'config.py')
        if os.path.exists(source_config):
            # 解析源配置文件
            imported_config = {}
            with open(source_config, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
                    if match:
                        var_name = match.group(1)
                        var_value_str = match.group(2)
                        try:
                            var_value = ast.literal_eval(var_value_str)
                            imported_config[var_name] = var_value
                        except:
                            imported_config[var_name] = var_value_str
            
            # 获取当前配置并合并
            current_config = parse_config()
            for key, value in imported_config.items():
                if key in current_config:  # 只更新当前配置中已存在的项
                    current_config[key] = value
            
            # 更新配置文件
            update_config(current_config)
            imported_items.append(f'config.py文件（导入了{len(imported_config)}个参数）')
        
        # 导入 prompts 文件夹
        source_prompts = os.path.join(source_dir, 'prompts')
        if os.path.exists(source_prompts):
            target_prompts = os.path.join(BASE_DIR, 'prompts')
            if os.path.exists(target_prompts):
                shutil.rmtree(target_prompts)
            shutil.copytree(source_prompts, target_prompts)
            imported_items.append('prompts文件夹')
        
        # 导入 emojis 文件夹
        source_emojis = os.path.join(source_dir, 'emojis')
        if os.path.exists(source_emojis):
            target_emojis = os.path.join(BASE_DIR, 'emojis')
            if os.path.exists(target_emojis):
                shutil.rmtree(target_emojis)
            shutil.copytree(source_emojis, target_emojis)
            imported_items.append('emojis文件夹')
        
        # 导入 forum_data 文件夹
        source_forum = os.path.join(source_dir, 'forum_data')
        if os.path.exists(source_forum):
            target_forum = FORUM_DATA_DIR
            if os.path.exists(target_forum):
                shutil.rmtree(target_forum)
            shutil.copytree(source_forum, target_forum)
            imported_items.append('forum_data文件夹')
        
        # 导入 CoreMemory 文件夹
        config = parse_config()
        core_memory_dirname = config.get('CORE_MEMORY_DIR', 'CoreMemory')
        source_core = os.path.join(source_dir, core_memory_dirname)
        if os.path.exists(source_core):
            target_core = os.path.join(BASE_DIR, core_memory_dirname)
            if os.path.exists(target_core):
                shutil.rmtree(target_core)
            shutil.copytree(source_core, target_core)
            imported_items.append('CoreMemory文件夹')
        
        # 导入 recurring_reminders.json 文件
        source_reminders = os.path.join(source_dir, 'recurring_reminders.json')
        if os.path.exists(source_reminders):
            target_reminders = os.path.join(BASE_DIR, 'recurring_reminders.json')
            shutil.copy2(source_reminders, target_reminders)
            imported_items.append('recurring_reminders.json文件')
        
        # 导入 chat_contexts.json 文件
        source_chat_contexts = os.path.join(source_dir, 'chat_contexts.json')
        if os.path.exists(source_chat_contexts):
            target_chat_contexts = os.path.join(BASE_DIR, 'chat_contexts.json')
            shutil.copy2(source_chat_contexts, target_chat_contexts)
            imported_items.append('chat_contexts.json文件')
        
        # 导入 Memory_Temp 文件夹
        config = parse_config()
        memory_temp_dirname = config.get('MEMORY_TEMP_DIR', 'Memory_Temp')
        source_memory_temp = os.path.join(source_dir, memory_temp_dirname)
        if os.path.exists(source_memory_temp):
            target_memory_temp = os.path.join(BASE_DIR, memory_temp_dirname)
            if os.path.exists(target_memory_temp):
                shutil.rmtree(target_memory_temp)
            shutil.copytree(source_memory_temp, target_memory_temp)
            imported_items.append('Memory_Temp文件夹')
        
        return imported_items
    except Exception as e:
        app.logger.error(f"导入目录数据失败: {str(e)}")
        raise Exception(f"导入失败: {str(e)}")

def import_files_data(files_dict):
    """从上传的文件字典导入数据"""
    imported_items = []
    
    try:
        # 创建临时目录来重建文件结构
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 重建文件结构
            for relative_path, file_data in files_dict.items():
                # 标准化路径分隔符
                relative_path = relative_path.replace('\\', '/')
                
                # 处理路径，去除顶级目录（如果有的话）
                path_parts = relative_path.split('/')
                if len(path_parts) > 1:
                    # 如果路径有多级，可能需要去除第一级目录
                    relative_path = '/'.join(path_parts[1:]) if path_parts[0] and path_parts[0] != '.' else relative_path
                
                # 跳过空路径
                if not relative_path:
                    continue
                
                # 创建完整的文件路径
                full_path = os.path.join(temp_dir, relative_path.replace('/', os.sep))
                
                # 确保目录存在
                dir_path = os.path.dirname(full_path)
                if dir_path and dir_path != temp_dir:
                    os.makedirs(dir_path, exist_ok=True)
                
                # 保存文件
                file_data.save(full_path)
                
                app.logger.debug(f"保存文件: {relative_path} -> {full_path}")
            
            # 使用现有的导入函数
            imported_items = import_directory_data(temp_dir)
            
            return imported_items
            
        finally:
            # 清理临时目录
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
                
    except Exception as e:
        app.logger.error(f"导入文件数据失败: {str(e)}")
        raise Exception(f"导入失败: {str(e)}")

@app.route('/import_full_directory', methods=['POST'])
@login_required
def import_full_directory():
    """导入完整的旧版本程序目录"""
    global bot_process
    
    # 如果 bot 正在运行，则不允许导入
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再导入数据'}), 400

    try:
        # 检查是否上传了文件
        if 'directory_files' not in request.files:
            return jsonify({'error': '未找到上传的目录文件'}), 400
            
        uploaded_files = request.files.getlist('directory_files')
        if not uploaded_files:
            return jsonify({'error': '未找到任何文件'}), 400
        
        # 检查是否包含config.py文件
        config_found = False
        files_dict = {}
        
        for file in uploaded_files:
            if file.filename:
                # 获取相对路径（webkitRelativePath）
                relative_path = file.filename
                files_dict[relative_path] = file
                
                # 检查是否有config.py
                if file.filename.endswith('config.py') or file.filename == 'config.py':
                    config_found = True
        
        if not config_found:
            return jsonify({'error': '选择的目录中没有找到config.py文件'}), 400
        
        # 创建备份目录
        backup_dir = create_backup_directory()
        
        # 备份现有数据
        backed_up_items = backup_existing_data(backup_dir)
        
        # 导入新数据
        imported_items = import_files_data(files_dict)
        
        # 构建结果消息
        message = f"完整目录导入成功！\n"
        message += f"共处理了 {len(uploaded_files)} 个文件\n"
        if backed_up_items:
            message += f"已备份的数据: {', '.join(backed_up_items)}\n"
        if imported_items:
            message += f"已导入的数据: {', '.join(imported_items)}\n"
        message += f"备份位置: {backup_dir}"
        
        return jsonify({
            'success': True, 
            'message': message,
            'backed_up_items': backed_up_items,
            'imported_items': imported_items,
            'backup_location': backup_dir,
            'files_count': len(uploaded_files)
        }), 200
                
    except Exception as e:
        app.logger.error(f"完整目录导入失败: {str(e)}")
        return jsonify({'error': f'导入失败: {str(e)}'}), 500

@app.route('/reset_default_config', methods=['POST'])
@login_required
def reset_default_config():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再恢复默认配置'}), 400
    
    try:
        # 获取默认配置
        default_config = get_default_config()
        
        # 保留当前的端口号和登录密码设置（避免被锁在外）
        current_config = parse_config()
        if 'PORT' in current_config:
            default_config['PORT'] = current_config['PORT']
        if 'LOGIN_PASSWORD' in current_config:
            default_config['LOGIN_PASSWORD'] = current_config['LOGIN_PASSWORD']
        if 'ENABLE_LOGIN_PASSWORD' in current_config:
            default_config['ENABLE_LOGIN_PASSWORD'] = current_config['ENABLE_LOGIN_PASSWORD']
        
        # 使用 update_config 函数来保留原有的注释和格式
        update_config(default_config)
        
        app.logger.info("配置已恢复到默认值")
        return jsonify({'message': '配置已恢复到默认值'}), 200
        
    except Exception as e:
        app.logger.error(f"恢复默认配置失败: {e}")
        return jsonify({'error': f'恢复默认配置失败: {str(e)}'}), 500

class WebLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        log_queue.put(log_entry)

# 配置日志处理器
web_handler = WebLogHandler()
web_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(web_handler)

@app.route('/stream')
@login_required
def stream():
    def event_stream():
        retry_count = 0
        while True:
            try:
                log = log_queue.get(timeout=5)
                yield f"data: {log}\n\n"
                retry_count = 0  # 成功时重置重试计数器
            except Empty:
                yield ":keep-alive\n\n"  # 发送心跳包
                retry_count = min(retry_count + 1, 5)
                time.sleep(2 ** retry_count)  # 指数退避
            except Exception as e:
                app.logger.error(f"SSE Error: {str(e)}")
                yield "event: error\ndata: Connection closed\n\n"
                break
    
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/api/log', methods=['POST'])
def receive_bot_log():
    try:
        # 增加Content-Type检查
        if not request.is_json:
            return jsonify({'error': 'Unsupported Media Type'}), 415

        # 支持两种格式：单个日志或日志数组
        if 'logs' in request.json:  # 批量日志
            logs_data = request.json.get('logs', [])
            if isinstance(logs_data, list):
                for log_entry in logs_data:
                    if log_entry:
                        colored_log = f"[BOT] \033[34m{mask_secrets(str(log_entry).strip())}\033[0m"
                        log_queue.put(colored_log)
                return jsonify({'status': 'success', 'processed': len(logs_data)})
            return jsonify({'error': 'Invalid logs format'}), 400
            
        elif 'log' in request.json:  # 兼容单条日志格式
            log_data = request.json.get('log')
            if log_data:
                colored_log = f"[BOT] \033[34m{mask_secrets(str(log_data).strip())}\033[0m"
                log_queue.put(colored_log)
            return jsonify({'status': 'success'})
            
        else:
            return jsonify({'error': 'Missing log data'}), 400
            
    except Exception as e:
        app.logger.error(f"日志接收失败: {str(e)}")
        return jsonify({'error': str(e)}), 500
def run_bat_file():
    bat_file_path = "一键检测.bat"
    if os.path.exists(bat_file_path):
        os.system(f"start {bat_file_path}")
@app.route('/run_one_key_detection', methods=['GET'])
def run_one_key_detection():
    bat_file_path = "一键检测.bat"
    if os.path.exists(bat_file_path):
        # 使用独立的进程运行 .bat 文件
        p = Process(target=run_bat_file)
        p.start()
        return """
        <h2>启动成功！</h2>
        <p>一键检测工具已成功启动！</p>
        <ul>
            <li>检测工具将在单独的端口上运行，并自动打开浏览器窗口显示检测结果。</li>
            <li>启动后，检测工具将在3分钟后自动关闭进程。</li>
        </ul>
        <h3>检测功能：</h3>
        <ul>
            <li>微信环境检测：检查微信版本、登录状态和窗口状态。</li>
            <li>API配置检测：验证API密钥和连接状态。</li>
            <li>系统资源检测：分析CPU、内存使用情况。</li>
            <li>生成详细的诊断报告：提供问题解决建议。</li>
        </ul>
        <p style="color: green; font-weight: bold;">提示：本页面可以安全关闭，检测工具将在后台运行。</p>
        """
    return """
    <h2>启动失败</h2>
    <p style="color: red;">未找到一键检测.bat，请检查路径是否正确。</p>
    <p>请确保<b>一键检测.bat</b>文件位于程序当前运行目录下。</p>
    """
@app.route('/bzwd')
@login_required
def show_bzwd_page():
    """打开bzwd.html页面"""
    try:
        # 如果需要给页面传递参数，可以在这里添加，比如：
        # config = parse_config()
        # return render_template('bzwd.html', config=config)
        return render_template('bzwd.html')
    except Exception as e:
        app.logger.error(f"加载bzwd.html页面失败: {e}")
        return "页面加载失败，请检查日志", 500
def get_default_config():
    return structured_default_config()

def validate_config():
    """确保本地结构化配置存在，并补齐缺失字段。"""
    try:
        cfg = load_structured_config()
        issues = validate_structured_config(cfg)
        missing = [item for item in issues if item.get("code") == "MISSING"]
        if missing:
            print(f"检测到{len(missing)}个缺失的配置项，已用默认值补齐")
            save_structured_config({})
        else:
            print("配置文件验证完成，所有配置项齐全")
        return bool(missing)
    except Exception as e:
        print(f"验证配置文件时出错: {str(e)}")
        return False


from forum_routes import forum_bp
app.register_blueprint(forum_bp)
from webui_data import register_data_routes
register_data_routes(app, login_required, sys.modules[__name__])
from operations_routes import register_operations_routes
register_operations_routes(app, login_required, BASE_DIR)
from operations_action_routes import register_operations_action_routes
register_operations_action_routes(app, login_required, BASE_DIR)

def kill_process_using_port(port):
    """
    检查指定端口是否被占用。
    仅结束本项目自己的历史 WebUI 进程；若是无关进程则提示冲突并退出，不误杀。
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        print(f"无效端口: {port}")
        return

    current_pid = os.getpid()
    project_dir = os.path.abspath(os.path.dirname(__file__))

    for conn in psutil.net_connections():
        if not conn.laddr or conn.laddr.port != port:
            continue
        if conn.status not in ('LISTEN', 'LISTENING'):
            continue
        if not conn.pid or conn.pid == current_pid:
            continue
        try:
            proc = psutil.Process(conn.pid)
            cmdline = ' '.join(proc.cmdline() or [])
            exe = proc.exe() or ''
            try:
                cwd = proc.cwd() or ''
            except Exception:
                cwd = ''
            haystack = f"{cmdline} {exe} {cwd}".lower()
            is_self = project_dir.lower() in haystack and (
                'config_editor.py' in haystack or 'config_editor.exe' in haystack
            )
            if is_self:
                print(f"检测到端口 {port} 被本项目历史进程 {conn.pid} 占用，尝试结束该进程……")
                proc.kill()
                proc.wait(timeout=3)
                print(f"进程 {conn.pid} 已被成功结束。")
            else:
                print(f"\033[31m端口 {port} 已被其他进程占用，未执行结束操作。\033[0m")
                print(f"  PID: {conn.pid}")
                print(f"  名称: {proc.name()}")
                print(f"  命令: {cmdline or exe}")
                print("请关闭该程序，或在 config.py 中修改 PORT 后重试。")
                sys.exit(1)
        except psutil.NoSuchProcess:
            continue
        except Exception as e:
            print(f"检查端口 {port} 占用进程时出现异常：{e}")

if __name__ == '__main__':
    # 配置应用日志级别
    app.logger.setLevel(logging.INFO)
    
    # 添加控制台处理器确保论坛相关日志显示
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    app.logger.addHandler(console_handler)
    
    class BotStatusFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            # 允许论坛相关的日志通过
            if '/forum/' in msg or 'forum' in msg.lower():
                return True
            # 如果日志消息中包含以下日志，则返回 False（不记录）
            if '/bot_status' in msg or \
               '/api/log' in msg or \
               '/save_all_reminders' in msg or \
               '/get_all_reminders' in msg or \
               '/api/get_chat_context_users' in msg or \
               '/bot_heartbeat' in msg:
                return False
            return True

    # 获取 werkzeug 的日志记录器并添加过滤器
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.addFilter(BotStatusFilter())

    # 验证配置文件完整性
    validate_config()
    config = parse_config()
    PORT = config.get('PORT', '5000')

    # 在启动服务器前检查端口是否被占用，若占用则结束该进程
    kill_process_using_port(PORT)

    print("\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print("\033[32m企业智能助手管理平台已启动\033[0m")
    print("\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print("")
    print(f"\033[36m访问地址: http://localhost:{config.get('PORT', '5000')}/\033[0m")
    print("\033[90m   浏览器将自动打开；如未打开请手动访问上述地址\033[0m")
    if config.get('ENABLE_LOGIN_PASSWORD', False):
        print("")
        print("\033[33m已启用登录保护\033[0m")
        print("\033[90m   请使用系统设置中配置的访问密码登录\033[0m")
    print("")
    print("\033[33m使用提示：\033[0m")
    print("\033[90m   1. 请先确认微信客户端已登录，再在页面中启动机器人\033[0m")
    print("\033[90m   2. 如出现循环发送，请立即点击「紧急停止」\033[0m")
    print("\033[90m   3. 配置修改后需先停止机器人再保存\033[0m")
    print("")
    print("\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    
    # 在启动服务器前设置定时器打开浏览器
    def open_browser():
        webbrowser.open(f'http://localhost:{PORT}/')
    
    Timer(1, open_browser).start()  # 延迟1秒确保服务器已启动

    # 根据配置决定绑定地址
    #host = "0.0.0.0" if config.get('ENABLE_LOGIN_PASSWORD', False) else "127.0.0.1"
    ignore_sigbreak_in_webui()
    app.logger.info("WEB_PID = %s", webui_pid())
    app.run(host= "127.0.0.1", debug=False, port=PORT, threaded=True, use_reloader=False)
    