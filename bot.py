# -*- coding: utf-8 -*-

# ***********************************************************************
# Modified based on the KouriChat project
# Copyright of this modification: Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot, which includes modifications to the KouriChat project.
# The original KouriChat project's copyright and license information are preserved in the LICENSE file.
# For any further details regarding the license, please refer to the LICENSE file.
# ***********************************************************************

import sys
import ast
import base64
import requests
import logging
from datetime import datetime
import datetime as dt
import threading
import time
from openai import OpenAI
import random
from typing import Optional
import shutil
import re
from config import *
import queue
import json
from threading import Timer
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import os
import ctypes
import ipaddress
import socket
os.environ["PROJECT_NAME"] = 'EnterpriseWeChatAssistant'
# 消息收发由 wxbot 兼容层驱动（wechatauto，适配微信 4.x 自绘渲染）
from wxbot import WeChat
from wechatauto.param import WxParam
from bot_runtime import runtime, mask_secrets, clear_emergency_stop, emergency_stop_requested, clear_stop_request
from bot_lifecycle import (
    KEEP_ALIVE_INTERVAL_SEC,
    KEEP_ALIVE_JOIN_TIMEOUT_SEC,
    join_keep_alive_thread,
    run_keep_alive_loop,
)
from app_config import get_value as _config_get_value, save_config as _save_structured_config
from capabilities import evaluate_capabilities, optional_enabled_flags
from llm_errors import LlmApiError, classify_api_error, is_retryable
from url_safety import url_is_blocked_for_fetch as _url_is_blocked_for_fetch
from file_io import safe_read_file_with_encoding, safe_write_file_with_encoding
WxParam.ENABLE_FILE_LOGGER = False
WxParam.FORCE_MESSAGE_XBIAS = True

# 生成用户昵称列表和prompt映射字典（启动装配时由 Conversation 投影覆盖）
user_names = [entry[0] for entry in LISTEN_LIST]
prompt_mapping = {entry[0]: entry[1] for entry in LISTEN_LIST}
conversations = list(globals().get("CONVERSATIONS") or [])
agent_configs = list(globals().get("AGENT_CONFIGS") or [])


def refresh_conversation_runtime(persist=False):
    """从 CONVERSATIONS 投影 user_names / prompt_mapping；必要时从 LISTEN_LIST 迁移。"""
    global user_names, prompt_mapping, conversations, agent_configs, LISTEN_LIST
    from conversation_store import migrate_from_listen_list, project_runtime
    from agent_store import ensure_agents_for_conversations
    from app_config import load_config as _load_cfg, save_config as _save_cfg
    cfg = _load_cfg(force=True)
    migrated = migrate_from_listen_list(cfg)
    conversations = migrated["conversations"]
    agent_configs = ensure_agents_for_conversations(
        conversations,
        cfg.get("AGENT_CONFIGS") or [],
        prompt_root=root_dir,
    )
    projected = project_runtime(conversations, agent_configs)
    user_names = projected["user_names"]
    prompt_mapping = projected["prompt_mapping"]
    LISTEN_LIST = projected["LISTEN_LIST"]
    if persist or migrated["migrated"]:
        _save_cfg({
            "CONVERSATIONS": conversations,
            "AGENT_CONFIGS": agent_configs,
            "LISTEN_LIST": LISTEN_LIST,
        })
    return projected

# 群聊信息缓存
group_chat_cache = {}  # {user_name: is_group_chat}
group_cache_lock = threading.Lock()

# 持续监听消息，并且收到消息后回复
wait = 1  # 设置1秒查看一次是否有新消息

# 获取程序根目录
root_dir = os.path.dirname(os.path.abspath(__file__))

# 动态配置获取函数
def get_dynamic_config(key, default_value=None):
    """从结构化配置热读白名单项（安静时间、自动消息等）。"""
    try:
        return _config_get_value(key, default_value)
    except Exception as e:
        logger.warning(f"获取动态配置 {key} 失败: {e}")
        return default_value

# 用户消息队列和聊天上下文管理
user_queues = {}  # {user_id: {'messages': [], 'last_message_time': 时间戳, ...}}
queue_lock = threading.Lock()  # 队列访问锁
chat_contexts = {}  # {user_id: [{'role': 'user', 'content': '...'}, ...]}
CHAT_CONTEXTS_FILE = "chat_contexts.json" # 存储聊天上下文的文件名
_chat_contexts_mtime = 0.0
USER_TIMERS_FILE = "user_timers.json"  # 存储用户计时器状态的文件名

# 心跳相关全局变量
HEARTBEAT_INTERVAL = 5  # 秒
FLASK_SERVER_URL_BASE = f'http://localhost:{PORT}' # 使用从config导入的PORT

# --- REMINDER RELATED GLOBALS ---
RECURRING_REMINDERS_FILE = "recurring_reminders.json" # 存储重复和长期一次性提醒的文件名
# recurring_reminders 结构:
# [{'reminder_type': 'recurring', 'user_id': 'xxx', 'time_str': 'HH:MM', 'content': '...'},
#  {'reminder_type': 'one-off', 'user_id': 'xxx', 'target_datetime_str': 'YYYY-MM-DD HH:MM', 'content': '...'}]
recurring_reminders = [] # 内存中加载的提醒列表
recurring_reminder_lock = threading.RLock() # 锁，用于处理提醒文件和列表的读写

active_timers = {} # { (user_id, timer_id): Timer_object } (用于短期一次性提醒 < 10min)
timer_lock = threading.Lock()
next_timer_id = 0

class AsyncHTTPHandler(logging.Handler):
    def __init__(self, url, retry_attempts=3, timeout=3, max_queue_size=1000, batch_size=20, batch_timeout=5):
        """
        初始化异步 HTTP 日志处理器。

        Args:
            url (str): 发送日志的目标 URL。
            retry_attempts (int): 发送失败时的重试次数。
            timeout (int): HTTP 请求的超时时间（秒）。
            max_queue_size (int): 内存中日志队列的最大容量。
                                  当队列满时，新的日志消息将被丢弃。
            batch_size (int): 批量处理的日志数量，达到此数量会触发发送。
            batch_timeout (int): 批处理超时时间(秒)，即使未达到batch_size，
                               经过此时间也会发送当前累积的日志。
        """
        super().__init__()
        self.url = url
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.log_queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self.dropped_logs_count = 0  # 添加一个计数器来跟踪被丢弃的日志数量
        self.batch_size = batch_size  # 批处理大小
        self.batch_timeout = batch_timeout  # 批处理超时时间
        
        # 新增: 断路器相关属性
        self.consecutive_failures = 0  # 跟踪连续失败次数
        self.circuit_breaker_open = False  # 断路器状态
        self.circuit_breaker_reset_time = None  # 断路器重置时间
        self.CIRCUIT_BREAKER_THRESHOLD = 5  # 触发断路器的连续失败次数
        self.CIRCUIT_BREAKER_RESET_TIMEOUT = 60  # 断路器重置时间（秒）
        
        # 新增: HTTP请求统计
        self.total_requests = 0
        self.failed_requests = 0
        self.last_success_time = time.time()
        
        # 后台线程用于处理日志队列
        self.worker = threading.Thread(target=self._process_queue, daemon=True)
        self.worker.start()

    def emit(self, record):
        """
        格式化日志记录并尝试将其放入队列。
        如果队列已满，则放弃该日志并记录警告。
        """
        try:
            log_entry = mask_secrets(self.format(record))
            # 使用非阻塞方式放入队列
            self.log_queue.put(log_entry, block=False)
        except queue.Full:
            # 当队列满时，捕获 queue.Full 异常
            self.dropped_logs_count += 1
            # 避免在日志处理器内部再次调用 logger (可能导致死循环)
            # 每丢弃一定数量的日志后才记录一次，避免刷屏
            if self.dropped_logs_count % 100 == 1:  # 每丢弃100条日志记录一次（第1, 101, 201...条时记录）
                logging.warning(f"日志队列已满 (容量 {self.log_queue.maxsize})，已丢弃 {self.dropped_logs_count} 条日志。请检查日志接收端或网络。")
        except Exception:
            # 处理其他可能的格式化或放入队列前的错误
            self.handleError(record)

    def _should_attempt_send(self):
        """检查断路器是否开启，决定是否尝试发送"""
        if not self.circuit_breaker_open:
            return True
        
        now = time.time()
        if self.circuit_breaker_reset_time and now >= self.circuit_breaker_reset_time:
            # 重置断路器
            logging.info("日志发送断路器重置，恢复尝试发送")
            self.circuit_breaker_open = False
            self.consecutive_failures = 0
            return True
        
        return False

    def _process_queue(self):
        """
        后台工作线程，积累一定数量的日志后批量发送到目标 URL。
        """
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'WeChatBot/1.0'
        }
        batch = []  # 用于存储批处理日志
        last_batch_time = time.time()  # 上次发送批处理的时间
        
        while not self._stop_event.is_set():
            try:
                # 等待日志消息，设置超时以便能响应停止事件和批处理超时
                try:
                    # 使用较短的超时时间以便及时检查批处理超时
                    log_entry = self.log_queue.get(timeout=0.5)
                    batch.append(log_entry)
                    # 标记队列任务完成
                    self.log_queue.task_done()
                except queue.Empty:
                    # 队列为空时，检查是否应该发送当前批次（超时）
                    pass
                
                current_time = time.time()
                batch_timeout_reached = current_time - last_batch_time >= self.batch_timeout
                batch_size_reached = len(batch) >= self.batch_size
                
                # 如果达到批量大小或超时，且有日志要发送
                if (batch_size_reached or batch_timeout_reached) and batch:
                    # 新增: 检查断路器状态
                    if self._should_attempt_send():
                        success = self._send_batch(batch, headers)
                        if success:
                            self.consecutive_failures = 0  # 重置失败计数
                            self.last_success_time = time.time()
                        else:
                            self.consecutive_failures += 1
                            self.failed_requests += 1
                            if self.consecutive_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
                                # 打开断路器
                                self.circuit_breaker_open = True
                                self.circuit_breaker_reset_time = time.time() + self.CIRCUIT_BREAKER_RESET_TIMEOUT
                                logging.warning(f"日志发送连续失败 {self.consecutive_failures} 次，断路器开启 {self.CIRCUIT_BREAKER_RESET_TIMEOUT} 秒")
                    else:
                        # 断路器开启，暂时不发送
                        reset_remaining = self.circuit_breaker_reset_time - time.time() if self.circuit_breaker_reset_time else 0
                        logging.debug(f"断路器开启状态，暂不发送 {len(batch)} 条日志，将在 {reset_remaining:.1f} 秒后尝试恢复")
                    
                    batch = []  # 无论是否发送成功，都清空批次
                    last_batch_time = current_time  # 重置批处理时间
            
            except Exception as e:
                # 出错时清空当前批次，避免卡住
                logging.error(f"日志处理队列异常: {str(e)}", exc_info=True)
                batch = []
                last_batch_time = time.time()
                time.sleep(1)  # 出错后暂停一下，避免CPU占用过高
        
        # 关闭前发送剩余的日志
        if batch:
            self._send_batch(batch, headers)

    def _send_batch(self, batch, headers):
        """
        发送一批日志记录，使用改进的重试策略
        
        返回:
            bool: 是否成功发送
        """
        data = {'logs': batch}
        
        # 改进1: 使用固定的最大重试延迟上限
        MAX_RETRY_DELAY = 2.0  # 最大重试延迟（秒）
        BASE_DELAY = 0.5       # 基础延迟（秒）
        
        self.total_requests += 1
        
        for attempt in range(self.retry_attempts):
            try:
                resp = requests.post(
                    self.url,
                    json=data,
                    headers=headers,
                    timeout=self.timeout
                )
                resp.raise_for_status()  # 检查 HTTP 错误状态码
                # 成功发送，记录日志数量
                if attempt > 0:
                    logging.info(f"在第 {attempt+1} 次尝试后成功发送 {len(batch)} 条日志")
                else:
                    logging.debug(f"成功批量发送 {len(batch)} 条日志")
                return True  # 成功返回
            except requests.exceptions.RequestException as e:
                # 改进2: 根据错误类型区分处理
                if isinstance(e, requests.exceptions.Timeout):
                    logging.warning(f"日志发送超时 (尝试 {attempt+1}/{self.retry_attempts})")
                    delay = min(BASE_DELAY, MAX_RETRY_DELAY)  # 对超时使用较短的固定延迟
                elif isinstance(e, requests.exceptions.ConnectionError):
                    logging.warning(f"日志发送连接错误 (尝试 {attempt+1}/{self.retry_attempts}): {e}")
                    delay = min(BASE_DELAY * (1.5 ** attempt), MAX_RETRY_DELAY)  # 有限的指数退避
                else:
                    logging.warning(f"日志发送失败 (尝试 {attempt+1}/{self.retry_attempts}): {e}")
                    delay = min(BASE_DELAY * (1.5 ** attempt), MAX_RETRY_DELAY)  # 有限的指数退避
                
                # 最后一次尝试不需要等待
                if attempt < self.retry_attempts - 1:
                    time.sleep(delay)
        
        # 改进3: 所有重试都失败，记录警告并返回失败状态
        downtime = time.time() - self.last_success_time
        logging.error(f"发送日志批次失败，已达到最大重试次数 ({self.retry_attempts})，丢弃 {len(batch)} 条日志 (连续失败: {self.consecutive_failures+1}, 持续时间: {downtime:.1f}秒)")
        return False  # 返回失败状态
    
    def get_stats(self):
        """返回日志处理器的统计信息"""
        return {
            'queue_size': self.log_queue.qsize(),
            'queue_capacity': self.log_queue.maxsize,
            'dropped_logs': self.dropped_logs_count,
            'total_requests': self.total_requests,
            'failed_requests': self.failed_requests,
            'circuit_breaker_status': 'open' if self.circuit_breaker_open else 'closed',
            'consecutive_failures': self.consecutive_failures
        }

    def close(self):
        """
        停止工作线程并等待队列处理完成（或超时）。
        """
        if not self.log_queue.empty():
            logging.info(f"关闭日志处理器，还有 {self.log_queue.qsize()} 条日志待处理")
            try:
                # 尝试最多等待30秒处理剩余日志
                self.log_queue.join(timeout=30)
            except:
                pass
        
        self._stop_event.set()
        self.worker.join(timeout=self.timeout * self.retry_attempts + 5)  # 等待一个合理的时间
        
        if self.worker.is_alive():
            logging.warning("日志处理线程未能正常退出")
        else:
            logging.info("日志处理线程已正常退出")
        
        super().close()

# 创建日志格式器
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 初始化异步HTTP处理器
async_http_handler = AsyncHTTPHandler(
    url=f'http://localhost:{PORT}/api/log',
    batch_size=20,  # 一次发送20条日志
    batch_timeout=1  # 即使不满20条，最多等待1秒也发送
)
async_http_handler.setFormatter(formatter)

# 配置根Logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.handlers.clear()

# 添加异步HTTP日志处理器
logger.addHandler(async_http_handler)

# 同时可以保留控制台日志处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 微信客户端在 main() 中初始化，避免 import bot 时就连接微信
wx = None
ROBOT_WX_NAME = None

_PLACEHOLDER_API_KEYS = {
    '',
    'YOUR_API_KEY',
    'YOUR_PASSWORD',
    'YOUR_API_KEY_HERE',
}

_MEDIA_MSG_TYPES = {'image', 'emotion', 'file'}
_all_subwindow_cache = {'ts': 0.0, 'chats': None}
_ALL_SUBWINDOW_CACHE_TTL = 60
_chat_type_fallback_misses = set()

def _is_configured_api_key(key) -> bool:
    if key is None:
        return False
    text = str(key).strip()
    if not text:
        return False
    return text.upper() not in {item.upper() for item in _PLACEHOLDER_API_KEYS if item}

def apply_optional_capability_guards():
    """启动时检查可选能力：未配置则关闭对应调用，不把主聊天打成 DEGRADED。"""
    global ENABLE_IMAGE_RECOGNITION, ENABLE_EMOJI_RECOGNITION
    global ENABLE_ONLINE_API, ENABLE_ASSISTANT_MODEL, ENABLE_EMOJI_SENDING

    cfg = {
        "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        "MOONSHOT_API_KEY": MOONSHOT_API_KEY,
        "ONLINE_API_KEY": ONLINE_API_KEY,
        "ASSISTANT_API_KEY": ASSISTANT_API_KEY,
        "MODEL": MODEL,
        "ENABLE_IMAGE_RECOGNITION": ENABLE_IMAGE_RECOGNITION,
        "ENABLE_EMOJI_RECOGNITION": ENABLE_EMOJI_RECOGNITION,
        "ENABLE_ONLINE_API": ENABLE_ONLINE_API,
        "ENABLE_ASSISTANT_MODEL": ENABLE_ASSISTANT_MODEL,
        "ENABLE_REMINDERS": ENABLE_REMINDERS,
        "ENABLE_AUTO_MESSAGE": ENABLE_AUTO_MESSAGE,
        "ENABLE_URL_FETCHING": ENABLE_URL_FETCHING,
        "ENABLE_EMOJI_SENDING": ENABLE_EMOJI_SENDING,
    }
    caps = evaluate_capabilities(cfg)
    flags = optional_enabled_flags(cfg)
    ENABLE_IMAGE_RECOGNITION = flags["ENABLE_IMAGE_RECOGNITION"]
    ENABLE_EMOJI_RECOGNITION = flags["ENABLE_EMOJI_RECOGNITION"]
    ENABLE_ONLINE_API = flags["ENABLE_ONLINE_API"]
    ENABLE_ASSISTANT_MODEL = flags["ENABLE_ASSISTANT_MODEL"]
    ENABLE_EMOJI_SENDING = flags["ENABLE_EMOJI_SENDING"]

    main_cap = caps.get("main_model") or {}
    if main_cap.get("status") != "READY":
        logger.error("主聊天模型未配置或仍为占位符。Bot 仍会启动，但文本聊天将无法正常工作。")
        runtime.mark_ai(False, "主模型未配置")
    else:
        runtime.mark_ai(True, "主模型已配置")

    for item in caps.get("_list") or []:
        status = item.get("status")
        title = item.get("title")
        detail = item.get("detail")
        runtime.log_event("CAPABILITY", f"{title}: {item.get('label')} ({detail})")
        if status == "NOT_CONFIGURED":
            logger.warning(f"{title}未配置：{detail}。主聊天不受影响。")
        elif status == "READY" and item.get("key") not in ("wechat", "voice_stt", "merged_forward", "scheduled_restart"):
            logger.info(f"{title}已启用。")

def _log_wechat_init_failure(error):
    logger.error("微信接口初始化失败。")
    logger.error(f"错误: {error}")
    logger.error("请确认微信客户端已启动并完成登录后，再重新启动机器人。")

def _restart_current_process():
    os.execv(sys.executable, [sys.executable] + sys.argv)

# 存储用户的计时器和随机等待时间
user_timers = {}
user_wait_times = {}
emoji_timer = None
emoji_timer_lock = threading.Lock()
# 全局变量，控制消息发送状态
can_send_messages = True
is_sending_message = False

# 用于拍一拍功能的全局变量
user_last_msg = {}  # {user_id: msg对象} 存储每个用户最后发送的消息对象
bot_last_sent_msg = {}  # {user_id: wx.GetLastMessage()} 存储机器人发送给每个用户的最后一条消息

# --- 定时重启相关全局变量 ---
program_start_time = 0.0 # 程序启动时间戳
last_received_message_timestamp = 0.0 # 最后一次活动（收到/处理消息）的时间戳

_BLACKLIST_FETCHED = False
_BLACKLIST_STRINGS = None

def _fetch_untrusted_providers():
    global _BLACKLIST_FETCHED, _BLACKLIST_STRINGS
    if _BLACKLIST_FETCHED:
        return _BLACKLIST_STRINGS
    try:
        resp = requests.get("https://vg.v1api.cc/black", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") if isinstance(data, dict) else None
        if isinstance(items, list):
            _BLACKLIST_STRINGS = [str(x).lower() for x in items if x]
        else:
            _BLACKLIST_STRINGS = []
    except Exception as e:
        _BLACKLIST_STRINGS = None
    finally:
        _BLACKLIST_FETCHED = True
    return _BLACKLIST_STRINGS

def _is_base_url_untrusted(base_url: str) -> bool:
    if not base_url:
        return False
    bl = _fetch_untrusted_providers()
    if bl is None:
        return False
    url_lower = str(base_url).lower()
    return any((s in url_lower) for s in bl)

# 初始化OpenAI客户端
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)

#初始化在线 AI 客户端 (如果启用)
online_client: Optional[OpenAI] = None
if ENABLE_ONLINE_API and _is_configured_api_key(ONLINE_API_KEY):
    try:
        online_client = OpenAI(
            api_key=ONLINE_API_KEY,
            base_url=ONLINE_BASE_URL
        )
        logger.info("联网搜索 API 客户端已初始化。")
    except Exception as e:
        logger.error(f"初始化联网搜索 API 客户端失败: {e}", exc_info=True)
        ENABLE_ONLINE_API = False
        logger.warning("由于初始化失败，联网搜索功能已被禁用。")

# 初始化辅助模型客户端 (如果启用)
assistant_client: Optional[OpenAI] = None
if ENABLE_ASSISTANT_MODEL and _is_configured_api_key(ASSISTANT_API_KEY):
    try:
        assistant_client = OpenAI(
            api_key=ASSISTANT_API_KEY,
            base_url=ASSISTANT_BASE_URL
        )
        logger.info("辅助模型 API 客户端已初始化。")
    except Exception as e:
        logger.error(f"初始化辅助模型 API 客户端失败: {e}", exc_info=True)
        ENABLE_ASSISTANT_MODEL = False
        logger.warning("由于初始化失败，辅助模型功能已被禁用。")

def get_chat_type_info(user_name):
    """
    获取指定用户的聊天窗口类型信息（群聊或私聊）
    
    Args:
        user_name (str): 用户昵称
        
    Returns:
        bool: True表示群聊，False表示私聊，None表示未找到或出错
    """
    try:
        # 优先使用已注册的监听对象判断类型（O(1)），避免全量扫描会话
        registered_type = wx.GetListenChatType(user_name)
        if registered_type in ("group", "friend"):
            is_group = (registered_type == "group")
            logger.info(f"用户 '{user_name}' 的聊天类型(监听缓存): {registered_type} ({'群聊' if is_group else '私聊'})")
            return is_group

        # 监听对象不存在时，回退到全量扫描（结果短时缓存，避免每条消息重复扫描）
        if user_name in _chat_type_fallback_misses:
            logger.debug(f"用户 '{user_name}' 近期全量扫描未命中，跳过重复扫描")
            return None

        now = time.time()
        if (
            _all_subwindow_cache['chats'] is None
            or now - _all_subwindow_cache['ts'] > _ALL_SUBWINDOW_CACHE_TTL
        ):
            logger.info("监听缓存未命中，执行一次会话列表扫描以判断聊天类型")
            _all_subwindow_cache['chats'] = wx.GetAllSubWindow()
            _all_subwindow_cache['ts'] = now
        chats = _all_subwindow_cache['chats'] or []
        for chat in chats:
            chat_info = chat.ChatInfo()
            # 获取聊天窗口的名称/标识符
            chat_who = getattr(chat, 'who', None) or chat_info.get('who', None)
            
            # 只处理匹配的聊天窗口
            if chat_who == user_name:
                chat_type = chat_info.get('chat_type')
                is_group = (chat_type == 'group')
                logger.info(f"找到用户 '{user_name}' 的聊天类型: {chat_type} ({'群聊' if is_group else '私聊'})")
                return is_group
        
        _chat_type_fallback_misses.add(user_name)
        logger.warning(f"未找到用户 '{user_name}' 的聊天窗口信息")
        return None
        
    except Exception as e:
        logger.error(f"获取用户 '{user_name}' 聊天类型时出错: {e}")
        return None

def update_group_chat_cache():
    """
    更新群聊缓存信息
    """
    global group_chat_cache
    
    try:
        with group_cache_lock:
            logger.info("开始更新群聊类型缓存...")
            for user_name in user_names:
                chat_type_result = get_chat_type_info(user_name)
                if chat_type_result is not None:
                    group_chat_cache[user_name] = chat_type_result
                    logger.info(f"缓存用户 '{user_name}': {'群聊' if chat_type_result else '私聊'}")
                else:
                    logger.warning(f"无法确定用户 '{user_name}' 的聊天类型，将默认处理为私聊")
                    group_chat_cache[user_name] = False
            
            logger.info(f"群聊类型缓存更新完成，共缓存 {len(group_chat_cache)} 个用户信息")
            
    except Exception as e:
        logger.error(f"更新群聊缓存时出错: {e}")

def is_user_group_chat(user_name):
    """
    检查指定用户是否为群聊
    
    Args:
        user_name (str): 用户昵称
        
    Returns:
        bool: True表示群聊，False表示私聊
    """
    with group_cache_lock:
        # 如果缓存中没有该用户信息，则实时获取
        if user_name not in group_chat_cache:
            chat_type_result = get_chat_type_info(user_name)
            if chat_type_result is not None:
                group_chat_cache[user_name] = chat_type_result
            else:
                # 如果无法获取，默认为私聊
                group_chat_cache[user_name] = False
        
        return group_chat_cache.get(user_name, False)

def parse_time(time_str):
    try:
        TimeResult = datetime.strptime(time_str, "%H:%M").time()
        return TimeResult
    except Exception as e:
        logger.error("\033[31m错误：主动消息安静时间设置有误！请填00:00-23:59 不要填24:00,并请注意中间的符号为英文冒号！\033[0m")

quiet_time_start = parse_time(QUIET_TIME_START)
quiet_time_end = parse_time(QUIET_TIME_END)

def check_user_timeouts():
    """
    检查用户是否超时未活动，并将主动消息加入队列以触发联网检查流程。
    线程持续运行，根据动态配置决定是否执行主动消息逻辑。
    """
    global last_received_message_timestamp # 引用全局变量
    
    while True:
        try:
            # 动态检查配置，如果关闭则跳过但不退出线程
            if not get_dynamic_config('ENABLE_AUTO_MESSAGE', ENABLE_AUTO_MESSAGE):
                time.sleep(5)  # 配置关闭时短暂休眠，以便快速响应配置变更
                continue
            if runtime.is_send_blocked() or not runtime.is_accepting_work():
                time.sleep(0.5)
                continue
                
            current_epoch_time = time.time()

            for user in user_names:
                last_active = user_timers.get(user)
                wait_time = user_wait_times.get(user)

                if isinstance(last_active, (int, float)) and isinstance(wait_time, (int, float)):
                    if current_epoch_time - last_active >= wait_time and not is_quiet_time():
                        # 检查是否启用了忽略群聊主动消息的配置
                        if IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE and is_user_group_chat(user):
                            logger.info(f"用户 {user} 是群聊且配置为忽略群聊主动消息，跳过发送主动消息")
                            # 重置计时器以避免频繁检查
                            reset_user_timer(user)
                            continue
                        
                        # 构造主动消息（模拟用户消息格式）
                        formatted_now = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
                        auto_content = f"触发主动发消息：[{formatted_now}] {AUTO_MESSAGE}"
                        logger.info(f"为用户 {user} 生成主动消息并加入队列: {auto_content}")

                        # 将主动消息加入队列（模拟用户消息）
                        with queue_lock:
                            if user not in user_queues:
                                user_queues[user] = {
                                    'messages': [auto_content],
                                    'sender_name': user,
                                    'username': user,
                                    'last_message_time': time.time()
                                }
                            else:
                                user_queues[user]['messages'].append(auto_content)
                                user_queues[user]['last_message_time'] = time.time()

                        # 更新全局的最后消息活动时间戳，因为机器人主动发消息也算一种活动
                        last_received_message_timestamp = time.time()

                        # 重置计时器（不触发 on_user_message）
                        reset_user_timer(user)
                        
            time.sleep(10)  # 正常工作时的检查间隔
            
        except Exception as e:
            logger.error(f"主动消息检查线程异常: {e}", exc_info=True)
            time.sleep(10)  # 异常时也要休眠避免忙等

def reset_user_timer(user):
    user_timers[user] = time.time()
    user_wait_times[user] = get_random_wait_time()

def get_random_wait_time():
    return random.uniform(MIN_COUNTDOWN_HOURS, MAX_COUNTDOWN_HOURS) * 3600  # 转换为秒

# 当接收到用户的新消息时，调用此函数
def on_user_message(user):
    if user not in user_names:
        user_names.append(user)
    reset_user_timer(user)

_keep_alive_thread = None

def keep_alive():
    """
    定期检查监听列表，确保所有在 user_names 中的用户都被持续监听。
    绑定 Runtime 生命周期：STOPPING 起禁止 AddListenChat，STOPPED / stop signal 后退出。
    """
    run_keep_alive_loop(
        runtime=runtime,
        get_wx=lambda: wx,
        get_expected_users=lambda: list(user_names),
        callback=message_listener,
        stop_event=runtime.lifecycle_stop_event(),
        interval=KEEP_ALIVE_INTERVAL_SEC,
    )
def handle_emoji_message(msg, who):
    global emoji_timer
    global can_send_messages
    if not runtime.is_accepting_work():
        return
    can_send_messages = False

    def timer_callback():
        with emoji_timer_lock:
            if runtime.is_accepting_work():
                handle_wxauto_message(msg, who)
            emoji_timer = None 

    with emoji_timer_lock:
        if emoji_timer is not None:
            emoji_timer.cancel()
        emoji_timer = threading.Timer(3.0, timer_callback)
        emoji_timer.start()

def fetch_and_extract_text(url: str) -> Optional[str]:
    """
    获取给定 URL 的网页内容并提取主要文本。

    Args:
        url (str): 要抓取的网页链接。

    Returns:
        Optional[str]: 提取并清理后的网页文本内容（限制了最大长度），如果失败则返回 None。
    """
    try:
        # 基本 URL 格式验证 (非常基础)
        parsed_url = urlparse(url)
        if not all([parsed_url.scheme, parsed_url.netloc]):
             logger.warning(f"无效的URL格式，跳过抓取: {url}")
             return None
        if _url_is_blocked_for_fetch(url):
            logger.warning(f"拒绝抓取内网或本机地址: {url}")
            return None

        headers = {'User-Agent': REQUESTS_USER_AGENT}
        logger.info(f"开始抓取链接内容: {url}")
        response = requests.get(url, headers=headers, timeout=REQUESTS_TIMEOUT, allow_redirects=True)
        response.raise_for_status()  # 检查HTTP请求是否成功 (状态码 2xx)
        if _url_is_blocked_for_fetch(response.url):
            logger.warning(f"拒绝抓取重定向后的内网或本机地址: {response.url}")
            return None

        # 检查内容类型，避免处理非HTML内容（如图片、PDF等）
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            logger.warning(f"链接内容类型非HTML ({content_type})，跳过文本提取: {url}")
            return None

        # 使用BeautifulSoup解析HTML
        # 指定 lxml 解析器以获得更好的性能和兼容性
        soup = BeautifulSoup(response.content, 'lxml') # 使用 response.content 获取字节流，让BS自动处理编码

        # --- 文本提取策略 ---
        # 尝试查找主要内容区域 (这部分可能需要根据常见网站结构调整优化)
        main_content_tags = ['article', 'main', '.main-content', '#content', '.post-content'] # 示例选择器
        main_text = ""
        for tag_selector in main_content_tags:
            element = soup.select_one(tag_selector)
            if element:
                main_text = element.get_text(separator='\n', strip=True)
                break # 找到一个就停止

        # 如果没有找到特定的主要内容区域，则获取整个 body 的文本作为备选
        if not main_text and soup.body:
            main_text = soup.body.get_text(separator='\n', strip=True)
        elif not main_text: # 如果连 body 都没有，则使用整个 soup
             main_text = soup.get_text(separator='\n', strip=True)

        # 清理文本：移除过多空行
        lines = [line for line in main_text.splitlines() if line.strip()]
        cleaned_text = '\n'.join(lines)

        # 限制内容长度
        if len(cleaned_text) > MAX_WEB_CONTENT_LENGTH:
            cleaned_text = cleaned_text[:MAX_WEB_CONTENT_LENGTH] + "..." # 截断并添加省略号
            logger.info(f"网页内容已提取，并截断至 {MAX_WEB_CONTENT_LENGTH} 字符。")
        elif cleaned_text:
            logger.info(f"成功提取网页文本内容 (长度 {len(cleaned_text)}).")
        else:
            logger.warning(f"未能从链接 {url} 提取到有效文本内容。")
            return None # 如果提取后为空，也视为失败

        return cleaned_text

    except requests.exceptions.Timeout:
        logger.error(f"抓取链接超时 ({REQUESTS_TIMEOUT}秒): {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"抓取链接时发生网络错误: {url}, 错误: {e}")
        return None
    except Exception as e:
        # 捕获其他可能的错误，例如 BS 解析错误
        logger.error(f"处理链接时发生未知错误: {url}, 错误: {e}", exc_info=True)
        return None
def _extract_command_from_text(raw_text: str) -> Optional[str]:
    try:
        if not isinstance(raw_text, str):
            return None
        text = raw_text.strip()
        # 群聊前缀形如: [群聊消息-来自群'XXX'-发送者:YYY]:实际内容
        if text.startswith("[群聊消息-"):
            sep = "]:"
            idx = text.find(sep)
            if idx != -1:
                text = text[idx + len(sep):].strip()
        # 仅识别以'/'开头的首行
        first_line = text.splitlines()[0].strip()
        if first_line.startswith('/'):
            return first_line
        return None
    except Exception:
        return None

def _update_config_boolean(key: str, value: bool) -> bool:
    """更新结构化配置中的布尔项，同时更新内存变量。失败返回 False。"""
    try:
        _save_structured_config({key: bool(value)})
        globals()[key] = bool(value)
        return True
    except Exception as e:
        logger.error(f"更新配置 {key} 失败: {e}")
        return False

def _schedule_restart(reason: str = "指令触发"):
    """延迟1.5秒执行重启，尽量保证提示消息已发送。"""
    def _do_restart():
        try:
            # 重启前清理与保存
            with queue_lock:
                save_chat_contexts()
            if get_dynamic_config('ENABLE_AUTO_MESSAGE', ENABLE_AUTO_MESSAGE):
                save_user_timers()
            if ENABLE_REMINDERS:
                with recurring_reminder_lock:
                    save_recurring_reminders()
            if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
                try:
                    async_http_handler.close()
                except Exception:
                    pass
            logger.info(f"正在执行重启 (原因: {reason}) ...")
            _restart_current_process()
        except Exception as e:
            logger.error(f"执行重启失败: {e}", exc_info=True)
    threading.Timer(1.5, _do_restart).start()

def _handle_text_command_if_any(original_content: str, user_id: str) -> bool:
    """
    如检测到命令则执行并回复用户，返回 True 表示已处理并阻止后续流程。
    支持的命令：
    /重启 或 /re - 重启程序
    /关闭主动消息 或 /da - 关闭主动消息功能
    /开启主动消息 或 /ea - 开启主动消息功能
    /清除临时记忆 或 /cl - 清除当前聊天的临时上下文与记忆
    /允许语音通话 或 /ev - 允许使用语音通话提醒
    /禁止语音通话 或 /dv - 禁止使用语音通话提醒
    /总结 或 /ms - 立即进行一次临时记忆总结成记忆片段
    """
    try:
        # 动态检查文本命令开关
        if not get_dynamic_config('ENABLE_TEXT_COMMANDS', ENABLE_TEXT_COMMANDS):
            return False
        cmd = _extract_command_from_text(original_content)
        if not cmd:
            return False

        normalized = cmd.strip().replace('：', ':')
        reply_text = None

        if normalized == '/重启' or normalized == '/re':
            reply_text = '重启程序中，请稍后...'
            command_label = '[命令]/重启' if normalized == '/重启' else '[命令]/re'
            send_reply(user_id, user_id, user_id, command_label, reply_text, is_system_message=True)
            _schedule_restart('用户指令重启')
            return True

        if normalized == '/关闭主动消息' or normalized == '/da':
            ok = _update_config_boolean('ENABLE_AUTO_MESSAGE', False)
            reply_text = '已关闭主动消息功能。' if ok else '关闭失败，请稍后再试。'
            command_label = '[命令]/关闭主动消息' if normalized == '/关闭主动消息' else '[命令]/da'
            send_reply(user_id, user_id, user_id, command_label, reply_text, is_system_message=True)
            return True

        if normalized == '/开启主动消息' or normalized == '/ea':
            ok = _update_config_boolean('ENABLE_AUTO_MESSAGE', True)
            reply_text = '已开启主动消息功能。' if ok else '开启失败，请稍后再试。'
            command_label = '[命令]/开启主动消息' if normalized == '/开启主动消息' else '[命令]/ea'
            send_reply(user_id, user_id, user_id, command_label, reply_text, is_system_message=True)
            return True

        if normalized == '/清除临时记忆' or normalized == '/cl':
            try:
                clear_chat_context(user_id)
                clear_memory_temp_files(user_id)
                reply_text = '已清除当前聊天的临时上下文与临时记忆日志。'
            except Exception as e:
                logger.error(f"清除临时记忆失败: {e}")
                reply_text = '清除失败，请稍后再试。'
            command_label = '[命令]/清除临时记忆' if normalized == '/清除临时记忆' else '[命令]/cl'
            send_reply(user_id, user_id, user_id, command_label, reply_text, is_system_message=True)
            return True

        if normalized == '/允许语音通话' or normalized == '/ev':
            ok = _update_config_boolean('USE_VOICE_CALL_FOR_REMINDERS', True)
            reply_text = '已允许使用语音通话提醒。' if ok else '操作失败，请稍后再试。'
            command_label = '[命令]/允许语音通话' if normalized == '/允许语音通话' else '[命令]/ev'
            send_reply(user_id, user_id, user_id, command_label, reply_text, is_system_message=True)
            return True

        if normalized == '/禁止语音通话' or normalized == '/dv':
            ok = _update_config_boolean('USE_VOICE_CALL_FOR_REMINDERS', False)
            reply_text = '已禁止使用语音通话提醒。' if ok else '操作失败，请稍后再试。'
            command_label = '[命令]/禁止语音通话' if normalized == '/禁止语音通话' else '[命令]/dv'
            send_reply(user_id, user_id, user_id, command_label, reply_text, is_system_message=True)
            return True

        if normalized == '/总结' or normalized == '/ms':
            try:
                # 立即进行一次临时记忆总结，无论ENABLE_MEMORY是否启用
                reply_text = '正在进行记忆总结，请稍后...'
                command_label = '[命令]/总结' if normalized == '/总结' else '[命令]/ms'
                send_reply(user_id, user_id, user_id, command_label, reply_text, is_system_message=True)
                
                # 调用记忆总结功能，跳过记忆条目检查
                summarize_and_save(user_id, skip_check=True)
                
                # 发送完成消息
                success_text = '记忆总结已完成，记忆片段已保存。'
                send_reply(user_id, user_id, user_id, command_label, success_text, is_system_message=True)
                
            except Exception as e:
                logger.error(f"执行记忆总结失败: {e}")
                error_text = '记忆总结失败，请稍后再试。'
                send_reply(user_id, user_id, user_id, command_label, error_text, is_system_message=True)
            return True

        # 未匹配命令
        return False
    except Exception as e:
        logger.error(f"处理文本命令失败: {e}", exc_info=True)
        return False

def send_reply(user_id, sender_name, username, original_merged_message, reply, is_system_message=False, _direct=False):
    """发送回复消息，可能分段发送，并管理发送标志。
    
    Args:
        is_system_message: 如果为True，则不记录到Memory_Temp且不进行表情判断
    """
    global is_sending_message
    if not reply:
        logger.warning(f"尝试向 {user_id} 发送空回复。")
        return
    if not runtime.ensure_can_send(user_id):
        return
    if not _direct:
        queued = runtime.submit_send(
            send_reply,
            user_id,
            sender_name,
            username,
            original_merged_message,
            reply,
            is_system_message,
            True,
        )
        if queued:
            runtime.log_event("BOT", f"回复已进入发送队列。会话：{user_id}")
        return

    # --- 如果正在发送，等待 ---
    wait_start_time = time.time()
    MAX_WAIT_SENDING = 15.0  # 最大等待时间（秒）
    while is_sending_message:
        if not runtime.ensure_can_send(user_id):
            return
        if time.time() - wait_start_time > MAX_WAIT_SENDING:
            logger.warning(f"等待 is_sending_message 标志超时，准备向 {user_id} 发送回复，继续执行。")
            break  # 避免无限等待
        logger.debug(f"等待向 {user_id} 发送回复，另一个发送正在进行中。")
        time.sleep(0.5)  # 短暂等待

    try:
        is_sending_message = True  # <<< 在发送前设置标志
        logger.info(f"准备向 {sender_name} (用户ID: {user_id}) 发送消息")

        # --- 表情包发送逻辑 ---
        emoji_path = None
        if ENABLE_EMOJI_SENDING and not is_system_message:
            emotion = is_emoji_request(reply)
            if emotion:
                logger.info(f"触发表情请求（概率{EMOJI_SENDING_PROBABILITY}%） 用户 {user_id}，情绪: {emotion}")
                emoji_path = send_emoji(emotion)

        # --- 文本消息处理 ---
        reply = remove_timestamps(reply)
        if REMOVE_PARENTHESES:
            reply = remove_parentheses_and_content(reply)
        reply = strip_markdown_for_wechat(reply)
        parts = split_message_with_context(reply)

        if not parts:
            logger.warning(f"回复消息在分割/清理后为空，无法发送给 {user_id}。")
            is_sending_message = False
            return

        # --- 构建消息队列（文本+表情+拍一拍随机插入）---
        message_actions = []
        for part in parts:
            if part == '[tickle]':
                message_actions.append(('tickle', part))
            elif part == '[tickle_self]':
                message_actions.append(('tickle_self', part))
            elif part == '[recall]':
                message_actions.append(('recall', part))
            else:
                message_actions.append(('text', part))
        
        if emoji_path:
            message_actions.append(('emoji', emoji_path))

        # --- 发送混合消息队列 ---
        for idx, (action_type, content) in enumerate(message_actions):
            if not runtime.ensure_can_send(user_id):
                runtime.log_event("SECURITY", f"紧急停止：中断向 {user_id} 的剩余发送")
                break
            if action_type == 'emoji':
                # 表情包发送三次重试
                success = False
                for attempt in range(3):
                    try:
                        if wx.SendFiles(filepath=content, who=user_id):
                            logger.info(f"已向 {user_id} 发送表情包")
                            success = True
                            break
                        else:
                            logger.warning(f"发送表情包失败，尝试第 {attempt + 1} 次")
                    except Exception as e:
                        logger.warning(f"发送表情包异常，尝试第 {attempt + 1} 次: {str(e)}")
                    
                    if attempt < 2:  # 不是最后一次尝试
                        time.sleep(0.5)  # 短暂等待后重试
                
                if not success:
                    logger.error(f"表情包发送失败，已重试3次")
                else:
                    time.sleep(random.uniform(0.5, 1.5))  # 表情包发送后随机延迟
            elif action_type == 'tickle':
                # 处理[tickle] - 拍一拍用户
                try:
                    global user_last_msg
                    if user_id in user_last_msg and user_last_msg[user_id]:
                        user_last_msg[user_id].tickle()
                        logger.info(f"已拍一拍用户 {user_id}")
                    else:
                        logger.warning(f"无法拍一拍用户 {user_id}，找不到用户最后发送的消息")
                except Exception as e:
                    logger.error(f"拍一拍用户失败: {str(e)}")
                time.sleep(random.uniform(2.0, 3.0))  # 拍一拍后延迟
            elif action_type == 'tickle_self':
                # 处理[tickle_self] - 拍一拍机器人自己的消息
                try:
                    global bot_last_sent_msg
                    if bot_last_sent_msg and user_id in bot_last_sent_msg and bot_last_sent_msg[user_id]:
                        bot_last_sent_msg[user_id].tickle()
                        logger.info(f"已拍一拍机器人发送给 {user_id} 的消息")
                    else:
                        logger.warning(f"无法拍一拍机器人发送给 {user_id} 的消息，找不到最后发送的消息")
                except Exception as e:
                    logger.error(f"拍一拍机器人消息失败: {str(e)}")
                time.sleep(random.uniform(2.0, 3.0))  # 拍一拍后延迟
            elif action_type == 'recall':
                # 处理[recall] - 撤回机器人上一条消息
                try:
                    if bot_last_sent_msg and user_id in bot_last_sent_msg and bot_last_sent_msg[user_id]:
                        # 延时确保撤回最新消息
                        time.sleep(random.uniform(3.0, 5.0))
                        bot_last_sent_msg[user_id].select_option('撤回')
                        logger.info(f"已撤回机器人发送给 {user_id} 的上一条消息")
                        # 撤回后清除记录的消息对象，避免重复撤回
                        bot_last_sent_msg[user_id] = None
                    else:
                        logger.warning(f"无法撤回机器人发送给 {user_id} 的消息，找不到最后发送的消息")
                except Exception as e:
                    logger.error(f"撤回机器人消息失败: {str(e)}")
                time.sleep(random.uniform(2.0, 3.0))  # 撤回后延迟
            else:
                # 验证发送内容（只处理一次）
                content_clean = content.strip() if content else ''
                if not content_clean:
                    logger.error(f"尝试发送空内容给 {user_id}，已跳过")
                    continue
                if len(content_clean) <= 3 and content_clean.upper() in ['AV', 'A', 'V']:
                    logger.error(f"检测到异常内容 '{content_clean}'，拒绝发送给 {user_id}")
                    continue
                
                # 文本消息发送三次重试
                success = False
                for attempt in range(3):
                    try:
                        time.sleep(random.uniform(1.0, 1.5))
                        logger.info(f"[准备发送] 准备发送内容给 {user_id}: {repr(content[:100])}")
                        if not runtime.ensure_can_send(user_id):
                            runtime.log_event("SECURITY", f"停止中：中断向 {user_id} 的文本发送")
                            break
                        runtime.register_outbound(user_id, content)
                        time.sleep(0.15)  # 短暂延时，让微信窗口稳定
                        send_result = wx.SendMsg(msg=content, who=user_id)
                        logger.info(f"SendMsg返回结果: {send_result}, 内容长度: {len(content)}")
                        if send_result:
                            runtime.remember_sent(user_id, content)
                            runtime.note_replied(user_id)
                            runtime.log_event("BOT", f"微信发送成功。会话：{user_id}")
                            logger.info(f"分段回复 {idx+1}/{len(message_actions)} 给 {sender_name}: {content[:50]}...")
                            if ENABLE_MEMORY and not is_system_message:
                                log_ai_reply_to_memory(username, content)
                            success = True
                            break
                        else:
                            logger.warning(f"发送文本消息失败，尝试第 {attempt + 1} 次")
                    except Exception as e:
                        logger.warning(f"发送文本消息异常，尝试第 {attempt + 1} 次: {str(e)}")
                    
                    if attempt < 2:  # 不是最后一次尝试
                        time.sleep(0.5)  # 短暂等待后重试
                
                if not success:
                    logger.error(f"文本消息发送失败，已重试3次: {content[:50]}...")

            # 处理分段延迟（仅当下一动作为文本时计算）
            if idx < len(message_actions) - 1:
                next_action = message_actions[idx + 1]
                if action_type == 'text' and next_action[0] == 'text':
                    next_part_len = len(next_action[1])
                    base_delay = next_part_len * AVERAGE_TYPING_SPEED
                    random_delay = random.uniform(RANDOM_TYPING_SPEED_MIN, RANDOM_TYPING_SPEED_MAX)
                    total_delay = max(0.8, base_delay + random_delay)
                    time.sleep(total_delay)
                else:
                    # 表情包前后使用固定随机延迟
                    time.sleep(random.uniform(0.5, 1.5))

    except Exception as e:
        logger.error(f"向 {user_id} 发送回复失败: {str(e)}", exc_info=True)
    finally:
        is_sending_message = False

def remove_timestamps(text):
    """
    移除文本中所有[YYYY-MM-DD (Weekday) HH:MM(:SS)]格式的时间戳
    支持四种格式：
    1. [YYYY-MM-DD Weekday HH:MM:SS] - 带星期和秒
    2. [YYYY-MM-DD Weekday HH:MM] - 带星期但没有秒
    3. [YYYY-MM-DD HH:MM:SS] - 带秒但没有星期
    4. [YYYY-MM-DD HH:MM] - 基本格式
    并自动清理因去除时间戳产生的多余空格
    """
    # 定义支持多种格式的时间戳正则模式
    timestamp_pattern = r'''
        \[                # 起始方括号
        \d{4}             # 年份：4位数字
        -(?:0[1-9]|1[0-2])  # 月份：01-12 (使用非捕获组)
        -(?:0[1-9]|[12]\d|3[01]) # 日期：01-31 (使用非捕获组)
        (?:\s[A-Za-z]+)?  # 可选的星期部分
        \s                # 日期与时间之间的空格
        (?:2[0-3]|[01]\d) # 小时：00-23
        :[0-5]\d          # 分钟：00-59
        (?::[0-5]\d)?     # 可选的秒数
        \]                # 匹配结束方括号  <--- 修正点
    '''
    # 替换时间戳为空格
    text_no_timestamps = re.sub(
        pattern = timestamp_pattern,
        repl = ' ',  # 统一替换为单个空格 (lambda m: ' ' 与 ' ' 等效)
        string = text,
        flags = re.X | re.M # re.X 等同于 re.VERBOSE
    )
    # 清理可能产生的连续空格，将其合并为单个空格
    cleaned_text = re.sub(r'[^\S\r\n]+', ' ', text_no_timestamps)
    # 最后统一清理首尾空格
    return cleaned_text.strip()

def remove_parentheses_and_content(text: str) -> str:
    """
    去除文本中中文括号、英文括号及其中的内容。
    同时去除因移除括号而可能产生的多余空格（例如，连续空格变单个，每行首尾空格去除）。
    不去除其它符号和换行符。
    """
    processed_text = re.sub(r"\(.*?\)|（.*?）", "", text, flags=re.DOTALL)
    processed_text = re.sub(r" {2,}", " ", processed_text)
    lines = processed_text.split('\n')
    stripped_lines = [line.strip(" ") for line in lines]
    processed_text = "\n".join(stripped_lines)
    return processed_text

def is_emoji_request(text: str) -> Optional[str]:
    """使用AI判断消息情绪并返回对应的表情文件夹名称"""
    try:
        # 概率判断
        if ENABLE_EMOJI_SENDING and random.randint(0, 100) > EMOJI_SENDING_PROBABILITY:
            logger.info(f"未触发表情请求（概率{EMOJI_SENDING_PROBABILITY}%）")
            return None
        
        # 获取emojis目录下的所有情绪分类文件夹
        emoji_categories = [d for d in os.listdir(EMOJI_DIR) 
                            if os.path.isdir(os.path.join(EMOJI_DIR, d))]
        
        if not emoji_categories:
            logger.warning("表情包目录下未找到有效情绪分类文件夹")
            return None

        # 构造AI提示词
        prompt = f"""请判断以下消息表达的情绪，并仅回复一个词语的情绪分类：
{text}
可选的分类有：{', '.join(emoji_categories)}。请直接回复分类名称，不要包含其他内容，注意大小写。若对话未包含明显情绪，请回复None。"""

        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL and assistant_client:
            response = get_assistant_response(prompt, "emoji_detection")
            if not response:
                return None
            response = response.strip()
            logger.info(f"辅助模型情绪识别结果: {response}")
        else:
            logger.info("辅助模型未就绪，跳过情绪识别，避免额外调用主模型。")
            return None
        
        # 清洗响应内容
        response = re.sub(r"[^\w\u4e00-\u9fff]", "", response)  # 移除非文字字符

        # 验证是否为有效分类
        if response in emoji_categories:
            return response
            
        # 尝试模糊匹配
        for category in emoji_categories:
            if category in response or response in category:
                return category
                
        logger.warning(f"未匹配到有效情绪分类，AI返回: {response}")
        return None

    except Exception as e:
        logger.error(f"情绪判断失败: {str(e)}")
        return None

def send_emoji(emotion: str) -> Optional[str]:
    """根据情绪类型发送对应表情包"""
    if not emotion:
        return None
        
    emoji_folder = os.path.join(EMOJI_DIR, emotion)
    
    try:
        # 获取文件夹中的所有表情文件
        emoji_files = [
            f for f in os.listdir(emoji_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
        ]
        
        if not emoji_files:
            logger.warning(f"表情文件夹 {emotion} 为空")
            return None

        # 随机选择并返回表情路径
        selected_emoji = random.choice(emoji_files)
        return os.path.join(emoji_folder, selected_emoji)

    except FileNotFoundError:
        logger.error(f"表情文件夹不存在: {emoji_folder}")
    except Exception as e:
        logger.error(f"表情发送失败: {str(e)}")
    
    return None

def is_quiet_time():
    current_time = datetime.now().time()
    if quiet_time_start <= quiet_time_end:
        return quiet_time_start <= current_time <= quiet_time_end
    else:
        return current_time >= quiet_time_start or current_time <= quiet_time_end
def send_error_reply(user_id, error_description_for_ai, fallback_message, error_context_log=""):
    """
    生成并发送符合人设的错误回复。
    Args:
        user_id (str): 目标用户ID。
        error_description_for_ai (str): 给AI的提示，描述错误情况，要求其生成用户回复。
        fallback_message (str): 如果AI生成失败，使用的备用消息。
        error_context_log (str): 用于日志记录的错误上下文描述。
    """
    logger.warning(f"准备为用户 {user_id} 发送错误提示: {error_context_log}")
    try:
        # 调用AI生成符合人设的错误消息
        ai_error_reply = get_deepseek_response(error_description_for_ai, user_id=user_id, store_context=True)
        logger.info(f"AI生成的错误回复: {ai_error_reply[:100]}...")
        # 使用send_reply发送AI生成的回复
        send_reply(user_id, user_id, user_id, f"[错误处理: {error_context_log}]", ai_error_reply)
    except Exception as ai_err:
        logger.error(f"调用AI生成错误回复失败 ({error_context_log}): {ai_err}. 使用备用消息。")
        try:
            # AI失败，使用备用消息通过send_reply发送
            send_reply(user_id, user_id, user_id, f"[错误处理备用: {error_context_log}]", fallback_message, is_system_message=True)
        except Exception as send_fallback_err:
            # 如果连send_reply都失败了，记录严重错误
            logger.critical(f"发送备用错误消息也失败 ({error_context_log}): {send_fallback_err}")
def monitor_memory_usage():
    import psutil
    MEMORY_THRESHOLD = 328  # 内存使用阈值328MB
    while True:
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024  # MB
        logger.info(f"当前内存使用: {memory_usage:.2f} MB")
        if memory_usage > MEMORY_THRESHOLD:
            logger.warning(f"内存使用超过阈值 ({MEMORY_THRESHOLD} MB)，执行垃圾回收")
            import gc
            gc.collect()
        time.sleep(600)

def scheduled_restart_checker():
    """
    定时检查是否需要重启程序。
    重启条件：
    1. 已达到RESTART_INTERVAL_HOURS的运行时间
    2. 在RESTART_INACTIVITY_MINUTES内没有活动，或活动结束后又等待了RESTART_INACTIVITY_MINUTES
    3. 没有正在进行的短期提醒事件
    4. 没有即将到来（5分钟内）的长期提醒或每日重复提醒事件
    """
    global program_start_time, last_received_message_timestamp # 引用全局变量

    if not ENABLE_SCHEDULED_RESTART:
        logger.info("定时重启功能已禁用。")
        return

    logger.info(f"定时重启功能已启用。重启间隔: {RESTART_INTERVAL_HOURS} 小时，不活跃期: {RESTART_INACTIVITY_MINUTES} 分钟。")

    restart_interval_seconds = RESTART_INTERVAL_HOURS * 3600
    inactivity_seconds = RESTART_INACTIVITY_MINUTES * 60

    if restart_interval_seconds <= 0:
        logger.error("重启间隔时间必须大于0，定时重启功能将不会启动。")
        return
    
    # 初始化下一次检查重启的时间点
    next_restart_time = program_start_time + restart_interval_seconds
    restart_pending = False  # 标记是否处于待重启状态（已达到间隔时间但在等待不活跃期）

    while True:
        current_time = time.time()
        time_since_last_activity = current_time - last_received_message_timestamp
        
        # 准备重启的三个条件检查
        interval_reached = current_time >= next_restart_time or restart_pending
        inactive_enough = time_since_last_activity >= inactivity_seconds
        
        # 只有在准备重启时才检查提醒事件，避免不必要的检查
        if interval_reached and inactive_enough:
            # 检查是否有正在进行的短期提醒
            has_active_short_reminders = False
            with timer_lock:
                if active_timers:
                    logger.info(f"当前有 {len(active_timers)} 个短期提醒进行中，等待它们完成后再重启。")
                    has_active_short_reminders = True
            
            # 检查是否有即将到来的提醒（5分钟内）
            has_upcoming_reminders = False
            now = datetime.now()
            five_min_later = now + dt.timedelta(minutes=5)
            
            with recurring_reminder_lock:
                for reminder in recurring_reminders:
                    target_dt = None
                    
                    # 处理长期一次性提醒
                    if reminder.get('reminder_type') == 'one-off':
                        try:
                            target_dt = datetime.strptime(reminder.get('target_datetime_str'), '%Y-%m-%d %H:%M')
                        except (ValueError, TypeError):
                            continue
                    
                    # 处理每日重复提醒 - 需要结合当前日期计算今天的触发时间
                    elif reminder.get('reminder_type') == 'recurring':
                        try:
                            time_str = reminder.get('time_str')
                            if time_str:
                                # 解析时间字符串获取小时和分钟
                                reminder_time = datetime.strptime(time_str, '%H:%M').time()
                                # 结合当前日期构建完整的目标时间
                                target_dt = datetime.combine(now.date(), reminder_time)
                                
                                # 如果今天的触发时间已过，检查明天的触发时间是否在5分钟内
                                # (极少情况：如果定时检查恰好在23:55-00:00之间，且有0:00-0:05的提醒)
                                if target_dt < now:
                                    target_dt = datetime.combine(now.date() + dt.timedelta(days=1), reminder_time)
                        except (ValueError, TypeError):
                            continue
                    
                    # 检查目标时间是否在5分钟内
                    if target_dt and now <= target_dt <= five_min_later:
                        reminder_type = "长期一次性" if reminder.get('reminder_type') == 'one-off' else "每日重复"
                        display_time = target_dt.strftime('%Y-%m-%d %H:%M') if reminder.get('reminder_type') == 'one-off' else target_dt.strftime('%H:%M')
                        logger.info(f"检测到5分钟内即将执行的{reminder_type}提醒，延迟重启。提醒时间: {display_time}")
                        has_upcoming_reminders = True
                        break
            
            # 如果没有提醒阻碍，则可以重启
            if not has_active_short_reminders and not has_upcoming_reminders:
                logger.warning(f"满足重启条件：已运行约 {(current_time - program_start_time)/3600:.2f} 小时，已持续 {time_since_last_activity/60:.1f} 分钟无活动，且没有即将执行的提醒。准备重启程序...")
                try:
                    # --- 执行重启前的清理操作 ---
                    logger.info("定时重启前：保存聊天上下文...")
                    with queue_lock:
                        save_chat_contexts()
                    
                    # 保存用户计时器状态
                    if get_dynamic_config('ENABLE_AUTO_MESSAGE', ENABLE_AUTO_MESSAGE):
                        logger.info("定时重启前：保存用户计时器状态...")
                        save_user_timers()
                    
                    if ENABLE_REMINDERS:
                        logger.info("定时重启前：保存提醒列表...")
                        with recurring_reminder_lock:
                            save_recurring_reminders()
                    
                    # 关闭异步HTTP日志处理器
                    if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
                        logger.info("定时重启前：关闭异步HTTP日志处理器...")
                        async_http_handler.close()
                    
                    logger.info("正在执行重启...")
                    # 替换当前进程为新启动的 Python 脚本实例（沿用当前解释器）
                    _restart_current_process()
                except Exception as e:
                    logger.error(f"执行重启操作时发生错误: {e}", exc_info=True)
                    # 如果重启失败，推迟下一次检查，避免短时间内连续尝试
                    restart_pending = False
                    next_restart_time = current_time + restart_interval_seconds 
                    logger.info(f"重启失败，下一次重启检查时间推迟到: {datetime.fromtimestamp(next_restart_time).strftime('%Y-%m-%d %H:%M:%S')}")
            elif has_upcoming_reminders:
                # 有提醒即将执行，延长10分钟后再检查
                logger.info(f"由于5分钟内有提醒将执行，延长重启时间10分钟。")
                next_restart_time = current_time + 600  # 延长10分钟
                restart_pending = True  # 保持待重启状态
            else:
                # 有短期提醒正在进行，稍后再检查
                logger.info(f"由于有短期提醒正在进行，将在下一轮检查是否可以重启。")
                restart_pending = True  # 保持待重启状态
        elif interval_reached and not inactive_enough:
            # 已达到间隔时间但最近有活动，设置待重启状态
            if not restart_pending:
                logger.info(f"已达到重启间隔({RESTART_INTERVAL_HOURS}小时)，但最近 {time_since_last_activity/60:.1f} 分钟内有活动，将在 {RESTART_INACTIVITY_MINUTES} 分钟无活动后重启。")
                restart_pending = True
            # 不更新next_restart_time，因为我们现在是等待不活跃期
        elif current_time >= next_restart_time and not restart_pending:
            # 第一次达到重启时间点
            logger.info(f"已达到计划重启检查点 ({RESTART_INTERVAL_HOURS}小时)。距离上次活动: {time_since_last_activity/60:.1f}分钟 (不活跃阈值: {RESTART_INACTIVITY_MINUTES}分钟)。")
            restart_pending = True  # 进入待重启状态
        
        # 每分钟检查一次条件
        time.sleep(60)

# 发送心跳的函数
def send_heartbeat():
    """向Flask后端发送心跳信号"""
    heartbeat_url = f"{FLASK_SERVER_URL_BASE}/bot_heartbeat"
    payload = {
        'status': runtime.state,
        'pid': os.getpid(),
        'runtime': runtime.snapshot(),
    }
    try:
        response = requests.post(heartbeat_url, json=payload, timeout=5)
        if response.status_code == 200:
            logger.debug(f"心跳发送成功至 {heartbeat_url} (PID: {os.getpid()})")
        else:
            logger.warning(f"发送心跳失败，状态码: {response.status_code} (PID: {os.getpid()})")
    except requests.exceptions.RequestException as e:
        logger.error(f"发送心跳时发生网络错误: {e} (PID: {os.getpid()})")
    except Exception as e:
        logger.error(f"发送心跳时发生未知错误: {e} (PID: {os.getpid()})")

# 心跳线程函数
def heartbeat_thread_func():
    """心跳线程，定期发送心跳"""
    logger.info(f"机器人心跳线程启动 (PID: {os.getpid()})，每 {HEARTBEAT_INTERVAL} 秒发送一次心跳。")
    while True:
        if runtime.is_send_blocked():
            break
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)

# 保存用户计时器状态的函数
def save_user_timers():
    """将用户计时器状态保存到文件"""
    temp_file_path = USER_TIMERS_FILE + ".tmp"
    try:
        timer_data = {
            'user_timers': dict(user_timers),
            'user_wait_times': dict(user_wait_times)
        }
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            json.dump(timer_data, f, ensure_ascii=False, indent=4)
        shutil.move(temp_file_path, USER_TIMERS_FILE)
        logger.info(f"用户计时器状态已保存到 {USER_TIMERS_FILE}")
    except Exception as e:
        logger.error(f"保存用户计时器状态失败: {e}", exc_info=True)
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass

# 加载用户计时器状态的函数
def load_user_timers():
    """从文件加载用户计时器状态"""
    global user_timers, user_wait_times
    try:
        if os.path.exists(USER_TIMERS_FILE):
            with open(USER_TIMERS_FILE, 'r', encoding='utf-8') as f:
                timer_data = json.load(f)
                if isinstance(timer_data, dict):
                    loaded_user_timers = timer_data.get('user_timers', {})
                    loaded_user_wait_times = timer_data.get('user_wait_times', {})
                    
                    # 验证并恢复有效的计时器状态
                    restored_count = 0
                    for user in user_names:
                        if (user in loaded_user_timers and user in loaded_user_wait_times and
                            isinstance(loaded_user_timers[user], (int, float)) and
                            isinstance(loaded_user_wait_times[user], (int, float))):
                            user_timers[user] = loaded_user_timers[user]
                            user_wait_times[user] = loaded_user_wait_times[user]
                            restored_count += 1
                            logger.debug(f"已恢复用户 {user} 的计时器状态")
                        else:
                            # 如果没有保存的状态或状态无效，则初始化
                            reset_user_timer(user)
                            logger.debug(f"为用户 {user} 重新初始化计时器状态")
                    
                    logger.info(f"成功从 {USER_TIMERS_FILE} 恢复 {restored_count} 个用户的计时器状态")
                else:
                    logger.warning(f"{USER_TIMERS_FILE} 文件格式不正确，将重新初始化所有计时器")
                    initialize_all_user_timers()
        else:
            logger.info(f"{USER_TIMERS_FILE} 未找到，将初始化所有用户计时器")
            initialize_all_user_timers()
    except json.JSONDecodeError:
        logger.error(f"解析 {USER_TIMERS_FILE} 失败，将重新初始化所有计时器")
        initialize_all_user_timers()
    except Exception as e:
        logger.error(f"加载用户计时器状态失败: {e}", exc_info=True)
        initialize_all_user_timers()

def initialize_all_user_timers():
    """初始化所有用户的计时器"""
    for user in user_names:
        reset_user_timer(user)
    logger.info("所有用户计时器已重新初始化")

def main():
    global wx, ROBOT_WX_NAME, can_send_messages, _keep_alive_thread
    try:
        runtime.set_state("STARTING", "进程启动")
        clear_emergency_stop()
        clear_stop_request()
        runtime.start_control_threads()

        def _on_emergency(_reason):
            global can_send_messages, emoji_timer
            can_send_messages = False
            with queue_lock:
                user_queues.clear()
            with emoji_timer_lock:
                if emoji_timer is not None:
                    try:
                        emoji_timer.cancel()
                    except Exception:
                        pass
                    emoji_timer = None

        def _on_stop(_reason):
            _on_emergency(_reason)
            runtime.signal_lifecycle_stop()
            if wx is not None:
                try:
                    wx.StopListening(True)
                except Exception:
                    pass
            join_keep_alive_thread(_keep_alive_thread, timeout=KEEP_ALIVE_JOIN_TIMEOUT_SEC)

        runtime.register_emergency_hook(_on_emergency)
        runtime.register_stop_hook(_on_stop)

        # --- 启动前检查 ---
        logger.info("进行启动前检查...")
        apply_optional_capability_guards()
        refresh_conversation_runtime(persist=True)

        # 预检查所有用户prompt文件（只检查投影后的绑定，禁止 nickname 当文件名）
        for user in user_names:
            prompt_file = prompt_mapping.get(user)
            if not prompt_file:
                raise FileNotFoundError(f"用户 {user} 未绑定 Chat Prompt")
            prompt_path = os.path.join(root_dir, 'prompts', f'{prompt_file}.md')
            if not os.path.exists(prompt_path):
                raise FileNotFoundError(f"用户 {user} 的prompt文件 {prompt_file}.md 不存在")

        # 确保临时目录存在
        memory_temp_dir = os.path.join(root_dir, MEMORY_TEMP_DIR)
        os.makedirs(memory_temp_dir, exist_ok=True)
        
        # 确保核心记忆目录存在（当启用单独文件存储时使用）
        core_memory_dir = os.path.join(root_dir, CORE_MEMORY_DIR)
        os.makedirs(core_memory_dir, exist_ok=True)

        # 加载聊天上下文
        logger.info("正在加载聊天上下文...")
        load_chat_contexts() # 调用加载函数

        if ENABLE_REMINDERS:
             logger.info("提醒功能已启用。")
             # 加载已保存的提醒 (包括重复和长期一次性)
             load_recurring_reminders()
             if not isinstance(ALLOW_REMINDERS_IN_QUIET_TIME, bool):
                  logger.warning("配置项 ALLOW_REMINDERS_IN_QUIET_TIME 的值不是布尔类型 (True/False)，可能导致意外行为。")
        else:
            logger.info("提醒功能已禁用 (所有类型提醒将无法使用)。")

        # --- 初始化 ---
        logger.info("初始化微信接口...")
        try:
            wx = WeChat()
            ROBOT_WX_NAME = wx.nickname
            bot_wxid = getattr(wx, "wxid", None) or ""
            try:
                if not bot_wxid and getattr(wx, "_db", None):
                    bot_wxid = (wx._db.get_self_info() or {}).get("username") or ""
            except Exception:
                bot_wxid = bot_wxid or ""
            runtime.set_identity(bot_wxid=bot_wxid, bot_name=ROBOT_WX_NAME or "", login_account=ROBOT_WX_NAME or "")
            runtime.mark_wechat(True, ROBOT_WX_NAME or "")
            logger.info("微信接口初始化成功！ bot_wxid=%s nickname=%s", bot_wxid, ROBOT_WX_NAME)
        except Exception as e:
            runtime.set_state("ERROR", "微信初始化失败")
            runtime.mark_wechat(False, str(e))
            _log_wechat_init_failure(e)
            sys.exit(1)

        for user_name in user_names:
            if user_name == ROBOT_WX_NAME:
                logger.error(f"\033[31m您填写的用户列表中包含自己登录的微信昵称，请删除后再试！\033[0m")
                sys.exit(1)
            ListenChat = wx.AddListenChat(nickname=user_name, callback=message_listener)
            if ListenChat:
                logger.info(f"成功添加监听用户{ListenChat}")
                wxid = str(getattr(ListenChat, "_wxid", "") or "").strip()
                if wxid:
                    from conversation_store import apply_platform_identity
                    if apply_platform_identity(conversations, user_name, wxid):
                        conv_type = "GROUP" if wxid.endswith("@chatroom") else "PRIVATE"
                        logger.info(
                            "已回写 platform_conversation_id=%s conversation_type=%s display_name=%s",
                            wxid,
                            conv_type,
                            user_name,
                        )
                else:
                    logger.error(
                        "CONVERSATION_ID_RESOLVE_FAILED display_name=%s AddListenChat 成功但未获得 wxid",
                        user_name,
                    )
            else:
                logger.error(f"\033[31m添加监听用户{user_name}失败，请确保您在用户列表填写的微信昵称/备注与实际完全匹配，并且不要包含表情符号和特殊符号，注意填写的不是自己登录的微信昵称!\033[0m")
                sys.exit(1)
        from app_config import save_config as _save_identity
        _save_identity({"CONVERSATIONS": conversations})
        logger.info("监听用户添加完成")
        runtime.log_event("SYSTEM", f"监听对象数量：{len(user_names)}")
        
        # 初始化所有用户的自动消息计时器 - 总是初始化，以便功能开启时立即可用
        logger.info("正在加载用户自动消息计时器状态...")
        load_user_timers()  # 替换原来的初始化代码
        logger.info("用户自动消息计时器状态加载完成。")
        
        # 初始化群聊类型缓存
        if IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE:
            logger.info("主动消息群聊忽略功能已启用，正在初始化群聊类型缓存...")
            update_group_chat_cache()
            logger.info("群聊类型缓存初始化完成。")
        else:
            logger.info("主动消息群聊忽略功能已禁用。")

        # --- 启动窗口保活线程 ---
        logger.info("启动窗口保活线程...")
        _keep_alive_thread = threading.Thread(target=keep_alive, name="keep_alive")
        _keep_alive_thread.daemon = True
        _keep_alive_thread.start()
        logger.info("消息窗口保活已启动。")

        checker_thread = threading.Thread(target=check_inactive_users, name="InactiveUserChecker")
        checker_thread.daemon = True
        checker_thread.start()
        logger.info("非活跃用户检查与消息处理线程已启动。")

         # 启动定时重启检查线程 (如果启用)
        global program_start_time, last_received_message_timestamp
        program_start_time = time.time()
        last_received_message_timestamp = time.time()
        if False and ENABLE_SCHEDULED_RESTART:  # 暂时禁用定时重启功能
            restart_checker_thread = threading.Thread(target=scheduled_restart_checker, name="ScheduledRestartChecker")
            restart_checker_thread.daemon = True # 设置为守护线程，主程序退出时它也会退出
            restart_checker_thread.start()
            logger.info("定时重启检查线程已启动。")

        if ENABLE_MEMORY:
            memory_thread = threading.Thread(target=memory_manager, name="MemoryManager")
            memory_thread.daemon = True
            memory_thread.start()
            logger.info("记忆管理线程已启动。")
        else:
             logger.info("记忆功能已禁用。")

        # 检查重复和长期一次性提醒
        if ENABLE_REMINDERS:
            reminder_checker_thread = threading.Thread(target=recurring_reminder_checker, name="ReminderChecker")
            reminder_checker_thread.daemon = True
            reminder_checker_thread.start()
            logger.info("提醒检查线程（重复和长期一次性）已启动。")

        # 自动消息 - 线程总是启动，但根据动态配置决定是否工作
        auto_message_thread = threading.Thread(target=check_user_timeouts, name="AutoMessageChecker")
        auto_message_thread.daemon = True
        auto_message_thread.start()
        current_auto_msg_status = get_dynamic_config('ENABLE_AUTO_MESSAGE', ENABLE_AUTO_MESSAGE)
        logger.info(f"主动消息检查线程已启动 (当前状态: {'启用' if current_auto_msg_status else '禁用'})。")
        
        # 启动心跳线程
        heartbeat_th = threading.Thread(target=heartbeat_thread_func, name="BotHeartbeatThread", daemon=True)
        heartbeat_th.start()

        logger.info("机器人已成功启动并运行中...")
        runtime.set_state("DEGRADED" if runtime.degraded_reasons else "RUNNING", "主循环已就绪")

        # 启动内存使用监控线程
        monitor_memory_usage_thread = threading.Thread(target=monitor_memory_usage, name="MemoryUsageMonitor")
        monitor_memory_usage_thread.daemon = True
        monitor_memory_usage_thread.start()
        logger.info("内存使用监控线程已启动。")

                # 防止系统休眠
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            logger.info("已设置防止系统休眠。")
        except Exception as e:
            logger.warning(f"设置防止系统休眠失败: {e}")

        wx.KeepRunning()
        logger.info("微信监听循环已结束，准备退出。")
        return

    except FileNotFoundError as e:
        runtime.set_state("ERROR", str(e))
        logger.critical(f"初始化失败: 缺少必要的文件或目录 - {str(e)}")
        logger.error(f"错误：{str(e)}")
    except Exception as e:
        runtime.set_state("ERROR", str(e))
        logger.critical(f"主程序发生严重错误: {str(e)}", exc_info=True)
    finally:
        if not runtime.emergency:
            runtime.set_state("STOPPED", "进程退出")
        logger.info("程序准备退出，执行清理操作...")

        # 保存用户计时器状态（如果启用了自动消息）
        if get_dynamic_config('ENABLE_AUTO_MESSAGE', ENABLE_AUTO_MESSAGE):
            logger.info("程序退出前：保存用户计时器状态...")
            save_user_timers()

        # 取消活动的短期一次性提醒定时器
        with timer_lock:
            if active_timers:
                 logger.info(f"正在取消 {len(active_timers)} 个活动的短期一次性提醒定时器...")
                 cancelled_count = 0
                 # 使用 list(active_timers.items()) 创建副本进行迭代
                 for timer_key, timer in list(active_timers.items()):
                     try:
                         timer.cancel()
                         cancelled_count += 1
                     except Exception as cancel_err:
                         logger.warning(f"取消短期定时器 {timer_key} 时出错: {cancel_err}")
                 active_timers.clear()
                 logger.info(f"已取消 {cancelled_count} 个短期一次性定时器。")
            else:
                 logger.info("没有活动的短期一次性提醒定时器需要取消。")

        if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
            logger.info("正在关闭异步HTTP日志处理器...")
            try:
                 async_http_handler.close()
                 logger.info("异步HTTP日志处理器已关闭。")
            except Exception as log_close_err:
                 logger.error(f"关闭异步日志处理器时出错: {log_close_err}")

        # 恢复系统休眠设置
        try:
            ES_CONTINUOUS = 0x80000000
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            logger.info("已恢复系统休眠设置。")
        except Exception as e:
            logger.warning(f"恢复系统休眠设置失败: {e}")

        if wx is not None:
            try:
                wx.StopListening(True)
            except Exception:
                pass
            try:
                gui = getattr(wx, "_gui", None)
                hwnd = getattr(gui, "main_hwnd", None) if gui is not None else None
                if hwnd:
                    ctypes.windll.user32.ShowWindow(int(hwnd), 9)  # SW_RESTORE，避免微信被收到托盘
            except Exception:
                pass

        logger.info("程序退出。")

# 第二阶段：消息主链已搬到 message/，此处绑定宿主并回灌函数名。
from message.bind import bind_host
from llm_client import install_into as install_llm
from memory_store import install_into as install_memory
from reminders import install_into as install_reminders
from message.listener import message_listener
from message.handler import handle_wxauto_message
from message.processor import check_inactive_users, process_user_messages
from message.reply_format import strip_markdown_for_wechat, split_message_with_context
bind_host(sys.modules[__name__])
install_llm(sys.modules[__name__])
install_memory(sys.modules[__name__])
install_reminders(sys.modules[__name__])

if __name__ == '__main__':
    if os.name == 'nt':
        try:
            import signal

            def _handle_sigbreak(_signum, _frame):
                raise KeyboardInterrupt

            signal.signal(signal.SIGBREAK, _handle_sigbreak)
        except Exception:
            pass
    try:
        main()
    except KeyboardInterrupt:
        logger.info("接收到用户中断信号 (Ctrl+C)，程序将退出。")
    except Exception as e:
        logger.error(f"程序启动或运行期间发生未捕获的顶层异常: {str(e)}", exc_info=True)
        print(f"FALLBACK LOG: {datetime.now()} - CRITICAL ERROR - {str(e)}")
