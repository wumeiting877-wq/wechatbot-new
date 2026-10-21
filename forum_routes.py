# -*- coding: utf-8 -*-
"""角色论坛 / NPC：从 config_editor 主链剥离的扩展模块。"""

from __future__ import annotations

import json
import os
import random
import uuid
import base64
import mimetypes
from datetime import datetime, timedelta
from flask import Blueprint, current_app, jsonify, render_template, request, send_file, session, redirect, url_for
from werkzeug.utils import secure_filename
import openai

forum_bp = Blueprint("forum", __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FORUM_DATA_DIR = os.path.join(BASE_DIR, 'forum_data')
FORUM_AVATAR_DIR = os.path.join(FORUM_DATA_DIR, 'avatar')


def _parse_config():
    from config_editor import parse_config
    return parse_config()


@forum_bp.before_request
def _forum_login_guard():
    config = _parse_config()
    if not config.get("ENABLE_LOGIN_PASSWORD", False):
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login"))


def _ensure_forum_dir_exists():
    try:
        os.makedirs(FORUM_DATA_DIR, exist_ok=True)
        os.makedirs(FORUM_AVATAR_DIR, exist_ok=True)
    except Exception as e:
        try:
            current_app.logger.error(f"创建论坛数据目录失败: {e}")
        except Exception:
            pass


def _npc_config_file_path():
    _ensure_forum_dir_exists()
    return os.path.join(FORUM_DATA_DIR, 'npc_config.json')

# ===== 头像文件处理函数 =====
def get_prompt_filename_by_character(character_name):
    """根据角色名获取对应的prompt文件名"""
    # 在论坛系统中，character_name就是prompt文件名
    # 因为LISTEN_LIST的结构是[微信名, prompt文件名]，
    # 而character_name就是从LISTEN_LIST[1]（即prompt文件名）获取的
    return character_name

def get_avatar_filename(character_name, file_extension):
    """生成头像文件名"""
    prompt_filename = get_prompt_filename_by_character(character_name)
    safe_filename = secure_filename(f"{prompt_filename}_avatar")
    return f"{safe_filename}.{file_extension}"

def allowed_avatar_file(filename):
    """检查文件是否为允许的图片格式"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_avatar_file_path(character_name):
    """获取头像文件路径"""
    _ensure_forum_dir_exists()
    prompt_filename = get_prompt_filename_by_character(character_name)
    safe_filename = secure_filename(f"{prompt_filename}_avatar")
    
    # 查找现有的头像文件
    for ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
        filepath = os.path.join(FORUM_AVATAR_DIR, f"{safe_filename}.{ext}")
        if os.path.exists(filepath):
            return filepath
    return None


@forum_bp.route('/api/npc/save_settings', methods=['POST'])
def save_npc_settings():
    """保存NPC配置"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': '无效的数据'}), 400
        
        current_app.logger.info(f"接收到NPC配置数据: {data}")
        
        # 保存NPC配置到文件
        npc_config_file = _npc_config_file_path()
        
        # 读取现有配置
        existing_config = {}
        if os.path.exists(npc_config_file):
            try:
                with open(npc_config_file, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
                current_app.logger.info(f"读取现有配置: {existing_config}")
            except Exception as read_error:
                current_app.logger.warning(f"读取现有配置失败，使用空配置: {read_error}")
                existing_config = {}
        
        # 更新配置 - 使用更精确的更新逻辑
        current_app.logger.info(f"接收到的数据: {data}")
        
        # 更新选中的NPC列表
        if 'selected_npcs' in data:
            existing_config['selected_npcs'] = data['selected_npcs']
            current_app.logger.info(f"更新选中的NPC列表: {data['selected_npcs']}")
        
        # 更新NPC设置
        if 'npc_settings' in data:
            if 'npc_settings' not in existing_config:
                existing_config['npc_settings'] = {}
            
            for npc_name, npc_data in data['npc_settings'].items():
                # 清理不需要的字段（移除 model_type）
                try:
                    if isinstance(npc_data, dict) and 'model_type' in npc_data:
                        npc_data.pop('model_type', None)
                except Exception:
                    pass
                
                existing_config['npc_settings'][npc_name] = npc_data
                current_app.logger.info(f"更新NPC {npc_name} 的设置: {npc_data}")

        
        current_app.logger.info(f"合并后的配置: {existing_config}")
        
        # 验证配置格式
        if 'selected_npcs' in existing_config and 'npc_settings' in existing_config:
            # 确保所有选中的NPC都有对应的设置
            for npc_name in existing_config['selected_npcs']:
                if npc_name not in existing_config['npc_settings']:
                    current_app.logger.warning(f"NPC {npc_name} 被选中但没有设置，将添加默认设置")
                    existing_config['npc_settings'][npc_name] = {
                        'language_style': 'casual',
                        'relationship': 'friend',
                        'example_output': '',
                        'other_settings': ''
                    }
                else:
                    current_app.logger.info(f"NPC {npc_name} 设置已更新")
        
        # 保存配置
        with open(npc_config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
        current_app.logger.info(f"成功保存NPC配置到文件: {npc_config_file}")
        
        # 验证保存是否成功
        try:
            with open(npc_config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
            current_app.logger.info(f"验证保存的配置: {saved_config}")
        except Exception as verify_error:
            current_app.logger.error(f"验证保存配置失败: {verify_error}")
            return jsonify({'error': '配置保存后验证失败'}), 500
        
        return jsonify({
            'success': True, 
            'message': 'NPC配置保存成功',
            'saved_config': saved_config
        })
        
    except Exception as e:
        current_app.logger.error(f"保存NPC配置失败: {e}")
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

@forum_bp.route('/api/npc/get_settings', methods=['GET'])
def get_npc_settings():
    """获取NPC配置"""
    try:
        npc_config_file = _npc_config_file_path()
        
        if os.path.exists(npc_config_file):
            try:
                with open(npc_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                current_app.logger.info(f"成功读取NPC配置: {config}")
                
                # 确保配置格式完整
                if 'selected_npcs' not in config:
                    config['selected_npcs'] = []
                if 'npc_settings' not in config:
                    config['npc_settings'] = {}
                
                # 为每个选中的NPC确保有默认设置
                for npc_name in config.get('selected_npcs', []):
                    if npc_name not in config.get('npc_settings', {}):
                        config['npc_settings'][npc_name] = {
                            'language_style': 'casual',
                            'relationship': 'friend',
                            'example_output': '',
                            'other_settings': ''
                        }
                        current_app.logger.info(f"为NPC {npc_name} 添加默认设置")
                    else:
                        # 清理不需要的字段（移除 model_type）
                        if isinstance(config['npc_settings'][npc_name], dict):
                            config['npc_settings'][npc_name].pop('model_type', None)
                        current_app.logger.info(f"NPC {npc_name} 已有设置: {config['npc_settings'][npc_name]}")
                
                return jsonify(config)
            except Exception as read_error:
                current_app.logger.error(f"读取NPC配置文件失败: {read_error}")
                return jsonify({'error': f'读取配置失败: {str(read_error)}'}), 500
        else:
            #current_app.logger.info("NPC配置文件不存在，返回空配置")
            return jsonify({
                'selected_npcs': [],
                'npc_settings': {}
            })
            
    except Exception as e:
        current_app.logger.error(f"获取NPC配置失败: {e}")
        return jsonify({'error': f'获取失败: {str(e)}'}), 500


@forum_bp.route('/forum/<character_name>')
def character_forum(character_name):
    """AI角色论坛页面"""
    try:
        config = _parse_config()
        
        # 验证角色名是否存在于配置中
        listen_list = config.get('LISTEN_LIST', [])
        character_found = False
        for item in listen_list:
            if len(item) >= 2 and item[1] == character_name:
                character_found = True
                break
        
        if not character_found:
            return "角色不存在", 404
        
        return render_template('character_forum.html', character_name=character_name)
    
    except Exception as e:
        current_app.logger.error(f"加载论坛页面失败: {e}")
        return "加载论坛页面失败", 500

@forum_bp.route('/api/forum/refresh/<character_name>', methods=['POST'])
def refresh_forum(character_name):
    """刷新论坛内容API"""
    try:
        config = _parse_config()
        
        # 验证角色名
        listen_list = config.get('LISTEN_LIST', [])
        character_found = False
        for item in listen_list:
            if len(item) >= 2 and item[1] == character_name:
                character_found = True
                break
        
        if not character_found:
            return jsonify({'error': '角色不存在'}), 404
        
        # 调用AI判断是否发论坛
        current_app.logger.info(f"开始为角色 {character_name} 刷新论坛")
        should_post, content = check_should_post_forum(character_name)
        current_app.logger.info(f"AI判断结果: should_post={should_post}, content='{content}'")
        
        if should_post:
            # 添加新论坛内容
            forum_post = add_forum_post(character_name, content)
            current_app.logger.info(f"成功添加论坛帖子: {forum_post['id'] if forum_post else 'None'}")
            return jsonify({
                'has_new_content': True,
                'post': forum_post
            })
        else:
            return jsonify({
                'has_new_content': False,
                'message': '暂时没有新的论坛动态'
            })
    
    except Exception as e:
        current_app.logger.error(f"刷新论坛失败: {e}")
        return jsonify({'error': f'刷新失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/posts/<character_name>')
def get_forum_posts(character_name):
    """获取论坛历史帖子"""
    try:
        config = _parse_config()
        
        posts = get_character_forum_posts(character_name)
        return jsonify({'posts': posts})
    
    except Exception as e:
        current_app.logger.error(f"获取论坛帖子失败: {e}")
        return jsonify({'error': f'获取失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/delete/<character_name>/<post_id>', methods=['DELETE'])
def delete_forum_post(character_name, post_id):
    """删除角色论坛帖子API"""
    try:
        current_app.logger.info(f"开始删除角色 {character_name} 的帖子 {post_id}")
        
        # 验证角色名
        config = _parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        character_found = False
        for item in listen_list:
            if len(item) >= 2 and item[1] == character_name:
                character_found = True
                break
        
        if not character_found:
            return jsonify({'error': '角色不存在'}), 404
        
        # 删除帖子
        success = delete_forum_post_by_id(character_name, post_id)
        
        if success:
            current_app.logger.info(f"成功删除帖子 {post_id}")
            return jsonify({'message': '删除成功'})
        else:
            current_app.logger.error(f"删除帖子 {post_id} 失败")
            return jsonify({'error': '帖子不存在或删除失败'}), 404
    
    except Exception as e:
        current_app.logger.error(f"删除论坛帖子失败: {e}")
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@forum_bp.route('/test_forum_ai/<character_name>')
def test_forum_ai(character_name):
    """测试AI论坛判断逻辑"""
    try:
        config = _parse_config()

        
        current_app.logger.info(f"测试AI判断逻辑，角色: {character_name}")
        should_post, content = check_should_post_forum(character_name)
        
        result = {
            "character": character_name,
            "should_post": should_post,
            "content": content,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return f"""
        <h2>AI判断测试结果</h2>
        <p><strong>角色:</strong> {character_name}</p>
        <p><strong>判断结果:</strong> {'发布' if should_post else '不发布'}</p>
        <p><strong>生成内容:</strong> {content}</p>
        <p><strong>测试时间:</strong> {result['timestamp']}</p>
        <hr>
        <p><a href="javascript:history.back()">返回</a> | <a href="/forum/{character_name}" target="_blank">查看论坛</a></p>
        """
        
    except Exception as e:
        current_app.logger.error(f"测试AI判断失败: {e}")
        return f"测试失败: {str(e)}", 500


def check_should_post_forum(character_name):
    """调用AI判断是否发论坛内容"""
    try:
        current_app.logger.info(f"检查角色 {character_name} 是否应该发布论坛内容")
        config = _parse_config()
        
        # 读取角色设定
        character_prompt = load_character_prompt(character_name)
        if not character_prompt:
            current_app.logger.warning(f"无法加载角色 {character_name} 的设定文件")
            return False, ""
        
        current_app.logger.info(f"成功加载角色设定，长度: {len(character_prompt)} 字符")
        
        # 构建AI提示
        current_time = datetime.now()
        time_str = current_time.strftime("%Y-%m-%d %H:%M")
        
        # 获取最近的论坛历史（用于避免重复）
        recent_posts = get_character_forum_posts(character_name, limit=5)
        recent_content = ""
        if recent_posts:
            recent_content = "\n最近发过的内容：\n" + "\n".join([f"- {post['content']}" for post in recent_posts[:3]])
        
        # --- 新增：50%概率的联网热点检索 ---
        import random
        online_hot_brief = ''
        should_use_online = random.random() < 0.5  # 50%概率
        
        if should_use_online and bool(config.get('ENABLE_ONLINE_API', False)):
            online_api_key = (config.get('ONLINE_API_KEY') or '').strip()
            online_base_url = config.get('ONLINE_BASE_URL', 'https://vg.v1api.cc/v1')
            online_model = config.get('ONLINE_MODEL', 'net-gpt-4o-mini')
            online_temperature = float(config.get('ONLINE_API_TEMPERATURE', 0.7))
            online_max_tokens = int(config.get('ONLINE_API_MAX_TOKEN', 2000))

            if online_api_key:
                try:
                    current_app.logger.info(f"尝试使用联网模型获取实时热点信息")
                    online_prompt = (
                        "请用简洁要点汇总'今天'中文互联网主要新闻与热点（3-5条），不要涉及政治敏感话题和政治人物。"
                        "偏向话题与趋势，不要细节长文；每条不超过30字；"
                        "只输出纯文本多行，不要编号、不要任何额外解释。"
                    )
                    online_client = openai.OpenAI(base_url=online_base_url, api_key=online_api_key, timeout=20)
                    online_completion = online_client.chat.completions.create(
                        model=online_model,
                        messages=[{"role": "user", "content": online_prompt}],
                        temperature=online_temperature,
                        max_tokens=min(online_max_tokens, 300),
                        timeout=20
                    )
                    online_hot_brief = (online_completion.choices[0].message.content or '').strip()
                    # 只保留前5行，避免上下文过长
                    if online_hot_brief:
                        lines_hot = [ln.strip() for ln in online_hot_brief.split('\n') if ln.strip()]
                        online_hot_brief = "\n".join(lines_hot[:5])
                        current_app.logger.info(f"成功获取联网热点信息，长度: {len(online_hot_brief)} 字符")
                except Exception as online_err:
                    current_app.logger.warning(f"联网热点检索失败，将使用常规生成: {online_err}")
                    online_hot_brief = ''
            else:
                current_app.logger.info("联网API密钥未配置，跳过热点检索")
        else:
            if should_use_online:
                current_app.logger.info("联网功能未启用，跳过热点检索")
            else:
                current_app.logger.info("本次未触发联网热点检索（50%概率）")
        
        # 构建融合热点的prompt
        if online_hot_brief:
            prompt = f"""
你有一个瞒着用户的小号推特账号，人设中的朋友圈人物都知道这个账号并会互动，你会在这里发一些比较真实的想法和日常。

角色设定：
{character_prompt}

当前时间：{time_str}
{recent_content}

今日热点参考（可选择性融合，避免机械复述，可以结合相关话题氛围发表个人感受）：
{online_hot_brief}

内容类型和tag使用：
1. 普通动态 - 直接发内容，不需要特殊标记
2. 备忘录类 - 用 #备忘录 tag
3. 情感宣泄 - 用 #心情 #想法 等tag
4. 日常记录 - 用 #日常 #生活 等tag
5. 重要事件 - 用 #记录 #重要 等tag
6. 热点评论 - 结合热点话题发表个人看法，可用相关tag

请根据角色性格和当前状态，可以结合今日热点话题（如果感兴趣），生成一条自然的推特动态。

要求：
- 情感表达直接、真实
- 具有活人感、可以适当结合网络热梗
- 短句不用句号
- 可以使用相关的tag（用#开头）
- 内容长度适中，像真实的推特发言
- 此次输出按一句或者一段话话，正常标点符号，不需要加反斜线
- 如果要评论热点，请结合个人角色特点和感受，不要流水账式复述

直接输出动态内容，不需要"内容："前缀。
"""
        else:
            prompt = f"""
你有一个瞒着用户的小号推特账号，人设中的朋友圈人物都知道这个账号并会互动，你会在这里发一些比较真实的想法和日常。

角色设定：
{character_prompt}

当前时间：{time_str}
{recent_content}

内容类型和tag使用：
1. 普通动态 - 直接发内容，不需要特殊标记
2. 备忘录类 - 用 #备忘录 tag
3. 情感宣泄 - 用 #心情 #想法 等tag
4. 日常记录 - 用 #日常 #生活 等tag
5. 重要事件 - 用 #记录 #重要 等tag

请根据角色性格和当前状态，随机选择一种内容类型，生成一条自然的推特动态。

要求：
- 情感表达直接、真实
- 具有活人感、可以适当结合网络热梗
- 短句不用句号
- 可以使用相关的tag（用#开头）
- 内容长度适中，像真实的推特发言
- 此次输出按一句或者一段话话，正常标点符号，不需要加反斜线

直接输出动态内容，不需要"内容："前缀。
"""

        # 打印完整提示词到控制台，方便调试
        print("\n" + "="*80)
        print(f"🎯 论坛拉取请求 - 角色: {character_name}")
        print("="*80)
        print(f"📊 提示词统计:")
        print(f"   角色设定长度: {len(character_prompt)} 字符")
        print(f"   总提示词长度: {len(prompt)} 字符")
        print(f"   当前时间: {time_str}")
        print(f"   最近内容数量: {len(recent_posts) if recent_posts else 0}")
        print(f"   联网热点检索: {'已启用' if online_hot_brief else '未启用'}")
        if online_hot_brief:
            print(f"   热点内容长度: {len(online_hot_brief)} 字符")
        print("="*80 + "\n")
        
        # 调用AI API - 优先使用论坛自定义模型，其次主模型
        use_forum_custom = bool(config.get('ENABLE_FORUM_CUSTOM_MODEL', False))
        if use_forum_custom:
            api_key = (config.get('FORUM_API_KEY') or config.get('DEEPSEEK_API_KEY', '')).strip()
            base_url = config.get('FORUM_BASE_URL', config.get('DEEPSEEK_BASE_URL', 'https://vg.v1api.cc/v1'))
            # 如果未填写论坛模型则回落到主模型
            model = (config.get('FORUM_MODEL') or config.get('MODEL', 'deepseek-v3-0324'))
            temperature = config.get('FORUM_TEMPERATURE', config.get('TEMPERATURE', 1.1))
            max_tokens = int(config.get('FORUM_MAX_TOKEN', config.get('MAX_TOKEN', 2000)))
        else:
            api_key = config.get('DEEPSEEK_API_KEY', '')
            base_url = config.get('DEEPSEEK_BASE_URL', 'https://vg.v1api.cc/v1')
            model = config.get('MODEL', 'deepseek-v3-0324')
            temperature = config.get('TEMPERATURE', 1.1)
            max_tokens = config.get('MAX_TOKEN', 2000)
        
        current_app.logger.info(f"准备调用AI API，模型: {model}, base_url: {base_url}")
        
        if not api_key:
            current_app.logger.error("API密钥未配置")
            return False, ""
        
        client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=30  # 设置30秒超时
        )
        
        current_app.logger.info("开始调用AI API...")
        completion = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": prompt
            }],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=30  # API调用超时设置
        )
        
        reply = completion.choices[0].message.content.strip()
        current_app.logger.info(f"AI回复: {reply}")
        
        # 打印AI响应到控制台，方便调试
        print(f"🤖 AI模型响应:")
        print(f"   模型: {model}")
        print(f"   联网热点: {'已使用' if online_hot_brief else '未使用'}")
        print(f"   响应内容: '{reply}'")
        print(f"   响应长度: {len(reply) if reply else 0} 字符")
        print(f"   是否为空: {'是' if not reply else '否'}")
        print("="*80 + "\n")
        
        # 简化的解析逻辑 - 直接使用AI的回复作为内容
        if reply and len(reply) > 5:
            # 清理可能的格式标记
            content = reply
            
            # 移除可能的"内容："前缀（如果AI还是加了的话）
            if content.startswith("内容：") or content.startswith("内容:"):
                content = content.split("：", 1)[-1].split(":", 1)[-1].strip()
            
            # 移除一些明显的格式字符
            content = content.replace("[具体的动态内容]", "").strip()
            
            # 自动替换反斜线为换行符
            content = content.replace("\\", "\n")
            
            if len(content) > 5:
                return True, content
        
        return False, ""
    
    except Exception as e:
        current_app.logger.error(f"调用AI判断论坛发布失败: {e}")
        # 如果API调用失败，生成一个简单的默认内容
        import random
        default_contents = [
            "今天心情不错呢~",
            "分享一下今天的小心情",
            "生活总是充满惊喜",
            "又是美好的一天",
            "想和大家分享一些想法",
            "今天有点特别的感觉",
            "心情很好，想说点什么",
            "日常的小确幸"
        ]
        return True, random.choice(default_contents)

def load_character_prompt(character_name):
    """读取角色设定文件"""
    try:
        prompt_file = os.path.join('prompts', f'{character_name}.md')
        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    except Exception as e:
        current_app.logger.error(f"读取角色设定失败: {e}")
        return None

def get_character_forum_posts(character_name, limit=20):
    """获取角色论坛帖子"""
    try:
        forum_file = _forum_file_path(character_name)
        if not os.path.exists(forum_file):
            return []
        
        with open(forum_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        posts = data.get('posts', [])
        # 按时间倒序排列
        posts.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return posts[:limit] if limit else posts
    
    except Exception as e:
        current_app.logger.error(f"获取论坛帖子失败: {e}")
        return []

def _forum_file_path(character_name):
    _ensure_forum_dir_exists()
    filename = f'forum_data_{character_name}.json'
    return os.path.join(FORUM_DATA_DIR, filename)

def load_forum_data(character_name):
    """加载论坛数据文件"""
    forum_file = _forum_file_path(character_name)
    if os.path.exists(forum_file):
        try:
            with open(forum_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {'posts': [], 'npcs': []}
    return {'posts': [], 'npcs': []}

def save_forum_data(character_name, data):
    """保存论坛数据文件（覆盖写入）"""
    forum_file = _forum_file_path(character_name)
    with open(forum_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _find_post_by_id(posts, post_id):
    for post in posts:
        if post.get('id') == post_id:
            return post
    return None

def toggle_like_forum_post(character_name, post_id, like_state=None):
    """切换或设置帖子点赞状态。like_state=None 表示切换；True/False 表示显式设置"""
    data = load_forum_data(character_name)
    posts = data.get('posts', [])
    post = _find_post_by_id(posts, post_id)
    if not post:
        return None
    current_liked = bool(post.get('liked_by_me', False))
    new_liked = (not current_liked) if like_state is None else bool(like_state)
    likes_count = int(post.get('likes', 0) or 0)
    if new_liked != current_liked:
        if new_liked:
            likes_count += 1
        else:
            likes_count = max(0, likes_count - 1)
        post['likes'] = likes_count
        post['liked_by_me'] = new_liked
        save_forum_data(character_name, data)
    return {'likes': post.get('likes', 0), 'liked_by_me': post.get('liked_by_me', False)}

def add_forum_comment(character_name, post_id, content, author_display_name=None):
    """为指定帖子添加一条评论。返回新评论对象。"""
    data = load_forum_data(character_name)
    posts = data.get('posts', [])
    post = _find_post_by_id(posts, post_id)
    if not post:
        return None
    if 'comments' not in post or not isinstance(post['comments'], list):
        post['comments'] = []
    now = datetime.now()
    comment = {
        'id': f"comment_{int(now.timestamp()*1000)}",
        'npc_name': author_display_name or f"{character_name} 的小号",
        'content': content,
        'timestamp': now.strftime("%Y-%m-%d %H:%M:%S"),
        'author': 'self'
    }
    post['comments'].append(comment)
    save_forum_data(character_name, data)
    return comment

def ensure_comment_ids_in_post(post):
    """为旧数据中的评论补充id字段"""
    if not post or 'comments' not in post:
        return
    for c in post.get('comments', []):
        if 'id' not in c:
            # 以时间戳或随机数填补
            c['id'] = f"comment_{int(time.time()*1000)}_{random.randint(100,999)}"

def add_forum_comment_with_parent(character_name, post_id, content, author, author_display, parent_comment_id=None):
    """为帖子添加一条评论，支持父评论。author: 'me' 或 'character'"""
    data = load_forum_data(character_name)
    posts = data.get('posts', [])
    post = _find_post_by_id(posts, post_id)
    if not post:
        return None
    if 'comments' not in post or not isinstance(post['comments'], list):
        post['comments'] = []
    ensure_comment_ids_in_post(post)
    now = datetime.now()
    comment = {
        'id': f"comment_{int(now.timestamp()*1000)}",
        'npc_name': author_display,
        'content': content,
        'timestamp': now.strftime("%Y-%m-%d %H:%M:%S"),
        'author': author,  # 'me' 或 'character'
    }
    if parent_comment_id:
        comment['parent_id'] = parent_comment_id
    post['comments'].append(comment)
    save_forum_data(character_name, data)
    return comment

def generate_character_conversation_reply(character_name, post_content, user_message):
    """基于角色设定，生成角色对用户的回复"""
    try:
        config = _parse_config()
        character_prompt = load_character_prompt(character_name) or ''
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        prompt = f"""
你是“{character_name}”，以下是你的角色设定：
{character_prompt}

场景：你的小号在社交平台发了一条动态，下面有一条来自用户的回复。请以你的人设与语气，回复用户的这条话。

原始动态：{post_content}
用户的话：{user_message}

要求：
1. 中文回复，口语化，贴近真实社交平台风格
2. 35字以内，尽量一到两句
3. 可以自然使用emoji但不要太多
4. 直接输出回复文本，不要任何前后缀
"""

        # 优先使用论坛自定义模型
        use_forum_custom = bool(config.get('ENABLE_FORUM_CUSTOM_MODEL', False))
        if use_forum_custom:
            api_key = (config.get('FORUM_API_KEY') or config.get('DEEPSEEK_API_KEY', '')).strip()
            base_url = config.get('FORUM_BASE_URL', config.get('DEEPSEEK_BASE_URL', 'https://vg.v1api.cc/v1'))
            model = (config.get('FORUM_MODEL') or config.get('MODEL', 'deepseek-v3-0324'))
            temperature = config.get('FORUM_TEMPERATURE', config.get('TEMPERATURE', 1.0))
            max_tokens = min(int(config.get('FORUM_MAX_TOKEN', config.get('MAX_TOKEN', 2000))), 120)
        else:
            api_key = config.get('DEEPSEEK_API_KEY', '')
            base_url = config.get('DEEPSEEK_BASE_URL', 'https://vg.v1api.cc/v1')
            model = config.get('MODEL', 'deepseek-v3-0324')
            temperature = config.get('TEMPERATURE', 1.0)
            max_tokens = min(config.get('MAX_TOKEN', 2000), 120)

        if not api_key:
            return "收到啦～"

        client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=20)
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=20
        )
        reply = completion.choices[0].message.content.strip()
        if not reply:
            reply = "收到啦～"
        # 基础清理
        if reply.startswith("回复：") or reply.startswith("回复:"):
            reply = reply.split("：", 1)[-1].split(":", 1)[-1].strip()
        reply = reply.replace("\\", "\n").strip()
        return reply[:100]
    except Exception as e:
        current_app.logger.error(f"生成角色会话回复失败: {e}")
        return "了解！"

def get_liked_forum_posts(character_name):
    data = load_forum_data(character_name)
    posts = data.get('posts', [])
    liked = [p for p in posts if p.get('liked_by_me')]
    # 保持与其他接口一致：按时间倒序
    try:
        liked.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    except Exception:
        pass
    return liked

def get_thread_posts(character_name):
    data = load_forum_data(character_name)
    posts = data.get('posts', [])
    threads = [p for p in posts if p.get('comments') and isinstance(p.get('comments'), list) and len(p.get('comments')) > 0]
    try:
        threads.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    except Exception:
        pass
    return threads

@forum_bp.route('/api/forum/like/<character_name>/<post_id>', methods=['POST'])
def like_forum_post(character_name, post_id):
    """点赞/取消点赞 指定帖子。请求体可包含 like: true/false；不含则为切换。"""
    try:
        like_state = None
        if request.is_json and isinstance(request.json, dict) and 'like' in request.json:
            like_state = bool(request.json.get('like'))
        result = toggle_like_forum_post(character_name, post_id, like_state)
        if not result:
            return jsonify({'error': '帖子不存在'}), 404
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"点赞操作失败: {e}")
        return jsonify({'error': f'点赞失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/likes/<character_name>')
def get_likes(character_name):
    """获取我喜欢的帖子列表"""
    try:
        posts = get_liked_forum_posts(character_name)
        return jsonify({'posts': posts})
    except Exception as e:
        current_app.logger.error(f"获取喜欢列表失败: {e}")
        return jsonify({'error': f'获取失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/reply/<character_name>/<post_id>', methods=['POST'])
def reply_to_post(character_name, post_id):
    """对帖子进行回复（添加一条评论），并自动生成角色的AI回复"""
    try:
        if not request.is_json:
            return jsonify({'error': '请求格式错误'}), 400
        content = str(request.json.get('content', '')).strip()
        parent_comment_id = request.json.get('parent_comment_id')
        if not content:
            return jsonify({'error': '回复内容不能为空'}), 400
        if len(content) > 500:
            return jsonify({'error': '回复内容过长（最多500字）'}), 400
        # 加载帖子用于上下文
        data = load_forum_data(character_name)
        post = _find_post_by_id(data.get('posts', []), post_id)
        if not post:
            return jsonify({'error': '帖子不存在，无法回复'}), 404

        ensure_comment_ids_in_post(post)

        # 先写入用户的评论
        my_comment = add_forum_comment_with_parent(
            character_name=character_name,
            post_id=post_id,
            content=content,
            author='me',
            author_display='我',
            parent_comment_id=parent_comment_id
        )

        # 生成角色AI回复
        ai_reply_text = generate_character_conversation_reply(
            character_name, post.get('content', ''), content
        )
        ai_comment = add_forum_comment_with_parent(
            character_name=character_name,
            post_id=post_id,
            content=ai_reply_text,
            author='character',
            author_display=f"{character_name} 的小号",
            parent_comment_id=my_comment['id']
        )

        return jsonify({'my_comment': my_comment, 'ai_comment': ai_comment})
    except Exception as e:
        current_app.logger.error(f"添加回复失败: {e}")
        return jsonify({'error': f'添加回复失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/threads/<character_name>')
def get_forum_threads(character_name):
    """获取包含回复的帖子列表（用于“推文和回复”）"""
    try:
        posts = get_thread_posts(character_name)
        # 为兼容旧数据，补全评论id
        for p in posts:
            ensure_comment_ids_in_post(p)
        return jsonify({'posts': posts})
    except Exception as e:
        current_app.logger.error(f"获取线程列表失败: {e}")
        return jsonify({'error': f'获取失败: {str(e)}'}), 500

# ===== 喜欢动态（AI生成） =====
def generate_likes_feed_items(character_name, use_online=False):
    """生成角色会喜欢的外部博文（AI生成，最多3条）。
    当启用联网模型时：先用联网模型检索“今日热点摘要”，再把摘要交给论坛模型（若启用）或主模型生成三条博文。
    """
    try:
        config = _parse_config()
        character_prompt = load_character_prompt(character_name) or ''
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # --- 阶段一：可选的联网热点检索 ---
        online_hot_brief = ''
        if use_online and bool(config.get('ENABLE_ONLINE_API', False)):
            online_api_key = (config.get('ONLINE_API_KEY') or '').strip()
            online_base_url = config.get('ONLINE_BASE_URL', 'https://vg.v1api.cc/v1')
            online_model = config.get('ONLINE_MODEL', 'net-gpt-4o-mini')
            online_temperature = float(config.get('ONLINE_API_TEMPERATURE', 0.7))
            online_max_tokens = int(config.get('ONLINE_API_MAX_TOKEN', 2000))

            if online_api_key:
                try:
                    online_prompt = (
                        "请用简洁要点汇总'今天'中文互联网主要新闻与热点（5-8条），不要涉及政治敏感话题和政治人物"
                        "偏向话题与趋势，不要细节长文；每条不超过30字；"
                        "只输出纯文本多行，不要编号、不要任何额外解释。"
                    )
                    online_client = openai.OpenAI(base_url=online_base_url, api_key=online_api_key, timeout=20)
                    online_completion = online_client.chat.completions.create(
                        model=online_model,
                        messages=[{"role": "user", "content": online_prompt}],
                        temperature=online_temperature,
                        max_tokens=min(online_max_tokens, 500),
                        timeout=20
                    )
                    online_hot_brief = (online_completion.choices[0].message.content or '').strip()
                    # 只保留前8行，避免上下文过长
                    if online_hot_brief:
                        lines_hot = [ln.strip() for ln in online_hot_brief.split('\n') if ln.strip()]
                        online_hot_brief = "\n".join(lines_hot[:8])
                except Exception as online_err:
                    current_app.logger.warning(f"联网热点检索失败，将回退本地生成: {online_err}")
                    online_hot_brief = ''

        # --- 阶段二：用论坛模型（若启用）或主模型生成三条内容 ---
        # 选择生成阶段所用模型
        gen_base_url = config.get('DEEPSEEK_BASE_URL', 'https://vg.v1api.cc/v1')
        gen_model = config.get('MODEL', 'deepseek-v3-0324')
        gen_api_key = (config.get('DEEPSEEK_API_KEY', '')).strip()
        gen_temperature = float(config.get('TEMPERATURE', 1.0))
        gen_max_tokens = min(int(config.get('MAX_TOKEN', 2000)), 400)

        if bool(config.get('ENABLE_FORUM_CUSTOM_MODEL', False)):
            gen_base_url = config.get('FORUM_BASE_URL', gen_base_url)
            gen_model = (config.get('FORUM_MODEL') or gen_model)
            gen_api_key = (config.get('FORUM_API_KEY') or gen_api_key).strip()
            gen_temperature = float(config.get('FORUM_TEMPERATURE', gen_temperature))
            gen_max_tokens = min(int(config.get('FORUM_MAX_TOKEN', gen_max_tokens)), 400)

        if not gen_api_key:
            # 无可用key，返回一些占位
            return [
                {'author': '热榜·话题', 'content': '今天的小确幸：晚霞好看到想停下脚步 #日常', 'timestamp': time_str},
                {'author': '城市·夜跑', 'content': '月亮今晚很好看，风也温柔，继续跑下去吧', 'timestamp': time_str},
            ]

        # 组合最终生成提示词
        if online_hot_brief:
            final_prompt = f"""
你在做内容聚合，给角色“{character_name}”挑选他会喜欢的3条中文博文（每条不超过60字）。
角色设定：
{character_prompt}

今日热点（仅作参考，避免机械复述，可融合相关话题与氛围）：
{online_hot_brief}

请严格按以下要求输出：
1) 仅输出三行内容，不要任何额外说明或序号
2) 每行格式：作者名 - 文本内容（可含#话题）
3) 不要使用反斜线 \\, 不要用 \n 或 \\ 分隔，直接正常标点与空格
4) 不要使用引号或代码块
"""
        else:
            final_prompt = f"""
你在做内容聚合，给角色“{character_name}”挑选他会喜欢的3条中文博文（每条不超过60字）。
角色设定：
{character_prompt}

如果具备联网能力，请结合当日热门趋势或资讯做简洁融合；否则输出贴合其性格与日常审美的生活化内容。

请严格按以下要求输出：
1) 仅输出三行内容，不要任何额外说明或序号
2) 每行格式：作者名 - 文本内容（可含#话题）
3) 不要使用反斜线 \\, 不要用 \n 或 \\ 分隔，直接正常标点与空格
4) 不要使用引号或代码块
"""

        gen_client = openai.OpenAI(base_url=gen_base_url, api_key=gen_api_key, timeout=25)
        gen_completion = gen_client.chat.completions.create(
            model=gen_model,
            messages=[{"role": "user", "content": final_prompt}],
            temperature=gen_temperature,
            max_tokens=gen_max_tokens,
            timeout=25
        )
        reply = (gen_completion.choices[0].message.content or '').strip()

        lines = [ln.strip() for ln in reply.split('\n') if ln.strip()]
        items = []
        for ln in lines[:3]:
            # 解析“作者 - 内容”
            if ' - ' in ln:
                author, content = ln.split(' - ', 1)
            elif '-' in ln:
                author, content = ln.split('-', 1)
            else:
                author, content = '博主', ln
            # 清理反斜线，保持单行
            safe_content = content.replace('\\', '').strip()
            items.append({
                'author': author.strip()[:20],
                'content': safe_content,
                'timestamp': time_str,
                'likes': random.randint(20, 500),
                'replies': random.randint(0, 120)
            })
        if not items:
            items = [{
                'author': '博主',
                'content': reply.replace('\\', '')[:60],
                'timestamp': time_str,
                'likes': random.randint(20, 500),
                'replies': random.randint(0, 120)
            }]
        return items
    except Exception as e:
        current_app.logger.error(f"生成喜欢Feed失败: {e}")
        return []

@forum_bp.route('/api/forum/likes_feed/<character_name>')
def get_likes_feed(character_name):
    try:
        data = load_forum_data(character_name)
        feed = data.get('liked_feed', [])
        # 补齐缺失的统计字段，便于老数据兼容
        changed = False
        for it in feed:
            if 'likes' not in it:
                it['likes'] = random.randint(20, 500)
                changed = True
            if 'replies' not in it:
                it['replies'] = random.randint(0, 120)
                changed = True
        if changed:
            save_forum_data(character_name, data)
        # 倒序（最新在前）
        try:
            feed.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        except Exception:
            pass
        return jsonify({'items': feed})
    except Exception as e:
        current_app.logger.error(f"获取喜欢Feed失败: {e}")
        return jsonify({'error': f'获取失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/refresh_likes/<character_name>', methods=['POST'])
def refresh_likes_feed(character_name):
    try:
        config = _parse_config()
        use_online = bool(config.get('ENABLE_ONLINE_API', False))
        items = generate_likes_feed_items(character_name, use_online=use_online)
        if not items:
            return jsonify({'has_new_content': False, 'message': '暂时没有新的喜欢'}), 200
        # 存储
        data = load_forum_data(character_name)
        if 'liked_feed' not in data or not isinstance(data['liked_feed'], list):
            data['liked_feed'] = []
        now_ts = int(time.time()*1000)
        for idx, it in enumerate(items):
            it['id'] = f"liked_{now_ts}_{idx}"
            if 'likes' not in it:
                it['likes'] = random.randint(20, 500)
            if 'replies' not in it:
                it['replies'] = random.randint(0, 120)
            data['liked_feed'].append(it)
        save_forum_data(character_name, data)
        return jsonify({'has_new_content': True, 'items': items})
    except Exception as e:
        current_app.logger.error(f"刷新喜欢Feed失败: {e}")
        return jsonify({'error': f'刷新失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/likes_feed/<character_name>/<item_id>', methods=['DELETE'])
def delete_likes_feed_item(character_name, item_id):
    """删除AI生成的喜欢Feed中的一项，不影响论坛原帖"""
    try:
        data = load_forum_data(character_name)
        feed = data.get('liked_feed', [])
        original_len = len(feed)
        feed = [it for it in feed if str(it.get('id')) != str(item_id)]
        if len(feed) == original_len:
            return jsonify({'error': '未找到该喜欢项'}), 404
        data['liked_feed'] = feed
        save_forum_data(character_name, data)
        return jsonify({'message': '已移除'}), 200
    except Exception as e:
        current_app.logger.error(f"删除喜欢Feed项失败: {e}")
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

# ===== 头像管理API =====
@forum_bp.route('/api/forum/avatar/upload/<character_name>', methods=['POST'])
def upload_avatar(character_name):
    """上传角色头像"""
    try:
        # 验证角色名
        config = _parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        character_found = False
        for item in listen_list:
            if len(item) >= 2 and item[1] == character_name:
                character_found = True
                break
        
        if not character_found:
            return jsonify({'error': '角色不存在'}), 404
        
        if 'avatar' not in request.files:
            return jsonify({'error': '没有上传文件'}), 400
        
        file = request.files['avatar']
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400
        
        if not allowed_avatar_file(file.filename):
            return jsonify({'error': '不支持的文件格式，请上传PNG、JPG、JPEG、GIF或WebP格式的图片'}), 400
        
        # 删除旧的头像文件
        old_avatar_path = get_avatar_file_path(character_name)
        if old_avatar_path and os.path.exists(old_avatar_path):
            try:
                os.remove(old_avatar_path)
                current_app.logger.info(f"删除旧头像文件: {old_avatar_path}")
            except Exception as e:
                current_app.logger.warning(f"删除旧头像文件失败: {e}")
        
        # 保存新的头像文件
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        filename = get_avatar_filename(character_name, file_extension)
        filepath = os.path.join(FORUM_AVATAR_DIR, filename)
        
        file.save(filepath)
        current_app.logger.info(f"头像上传成功: {filepath}")
        
        return jsonify({
            'message': '头像上传成功',
            'filename': filename
        })
    
    except Exception as e:
        current_app.logger.error(f"头像上传失败: {e}")
        return jsonify({'error': f'上传失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/avatar/<character_name>')
def get_avatar(character_name):
    """获取角色头像"""
    try:
        avatar_path = get_avatar_file_path(character_name)
        if not avatar_path:
            return jsonify({'error': '头像不存在'}), 404
        
        return send_file(avatar_path)
    
    except Exception as e:
        current_app.logger.error(f"获取头像失败: {e}")
        return jsonify({'error': f'获取失败: {str(e)}'}), 500

@forum_bp.route('/api/forum/avatar/<character_name>', methods=['DELETE'])
def delete_avatar(character_name):
    """删除角色头像"""
    try:
        # 验证角色名
        config = _parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        character_found = False
        for item in listen_list:
            if len(item) >= 2 and item[1] == character_name:
                character_found = True
                break
        
        if not character_found:
            return jsonify({'error': '角色不存在'}), 404
        
        avatar_path = get_avatar_file_path(character_name)
        if not avatar_path:
            return jsonify({'error': '头像不存在'}), 404
        
        os.remove(avatar_path)
        current_app.logger.info(f"头像删除成功: {avatar_path}")
        
        return jsonify({'message': '头像删除成功'})
    
    except Exception as e:
        current_app.logger.error(f"头像删除失败: {e}")
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

def add_forum_post(character_name, content):
    """添加新的论坛帖子"""
    try:
        forum_file = _forum_file_path(character_name)
        
        # 读取现有数据
        if os.path.exists(forum_file):
            with open(forum_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {'posts': [], 'npcs': []}
        
        # 创建新帖子
        now = datetime.now()
        new_post = {
            'id': f"post_{int(now.timestamp())}",
            'content': content,
            'timestamp': now.strftime("%Y-%m-%d %H:%M:%S"),
            'likes': random.randint(5, 50),
            'comments': []
        }
        
        # 生成NPC评论：在生成函数内部对每个NPC进行独立概率判定
        npc_comments = generate_npc_comments(character_name, content)
        new_post['comments'] = npc_comments
        
        # 添加到数据中
        data['posts'].append(new_post)
        
        # 保持最多100条帖子
        if len(data['posts']) > 100:
            data['posts'] = data['posts'][-100:]
        
        # 保存数据
        with open(forum_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return new_post
    
    except Exception as e:
        current_app.logger.error(f"添加论坛帖子失败: {e}")
        return None

def generate_npc_comments(character_name, post_content):
    """生成NPC评论 - 基于用户配置的NPC设定和回复风格"""
    try:
        # 从角色设定中提取可能的NPC名单
        character_prompt = load_character_prompt(character_name)
        
        # 尝试从角色设定中提取人物名称
        extracted_names = []
        if character_prompt:
            import re
            # 查找可能的人名（中文姓名模式）
            name_patterns = [
                r'([小]\w{1,2})',  # 小桃、小明等
                r'([李王张刘陈杨黄赵吴周徐孙朱马胡郭何高林罗郑梁谢宋唐许邓冯韩曹曾彭肖蔡潘田董袁于余叶蒋杜苏魏程吕丁沈任姚卢姜崔钟谭陆汪范金石廖贾夏韦傅方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤]\w{1,2})',  # 常见姓氏
                r'(\w{2,3}(?:同学|朋友|室友|同事))',  # XX同学、XX朋友等
            ]
            
            for pattern in name_patterns:
                matches = re.findall(pattern, character_prompt)
                extracted_names.extend(matches)
        

        # 合并名单，优先使用从角色设定中提取的名称
        all_names = list(set(extracted_names ))
        
        # 尝试读取用户配置的NPC设定
        npc_config = load_npc_config()
        configured_npcs = []
        
        if npc_config and 'selected_npcs' in npc_config:
            for npc_name in npc_config['selected_npcs']:
                if npc_name in npc_config.get('npc_settings', {}):
                    npc_settings = npc_config['npc_settings'][npc_name]
                    configured_npcs.append({
                        'name': npc_name,
                        'settings': npc_settings
                    })
        
        # 只使用用户配置的NPC生成智能回复
        if configured_npcs:
            current_app.logger.info(f"使用配置的NPC生成智能回复: {[npc['name'] for npc in configured_npcs]}")
            return generate_configured_npc_comments(configured_npcs, post_content, character_name)
        
        # 如果没有配置NPC，返回空列表
        current_app.logger.info("未配置NPC，不生成评论")
        return []
        
    except Exception as e:
        current_app.logger.error(f"生成NPC评论失败: {e}")
        return []

def generate_configured_npc_comments(configured_npcs, post_content, character_name):
    """基于用户配置生成智能NPC评论（逐条串行，每个NPC独立60%概率）"""
    try:
        comments = []
        reply_probability = 0.6  # 每个NPC独立回复概率

        # 逐条串行生成，避免并行导致的潜在超时/限速问题
        for npc in configured_npcs:
            # 概率判定：每个NPC独立60%概率回复
            if random.random() >= reply_probability:
                continue

            npc_name = npc['name']
            npc_settings = npc['settings']

            # 基于配置生成智能回复（串行调用）
            comment_text = generate_smart_npc_reply(
                npc_name,
                npc_settings,
                post_content,
                character_name
            )

            if comment_text:
                # 随机延迟时间
                base_time = datetime.now()
                delay_minutes = random.randint(2, 120)  # 2分钟到2小时
                comment_time = base_time + timedelta(minutes=delay_minutes)

                comments.append({
                    'npc_name': npc_name,
                    'content': comment_text,
                    'timestamp': comment_time.strftime("%Y-%m-%d %H:%M:%S")
                })

        return comments

    except Exception as e:
        current_app.logger.error(f"生成配置NPC评论失败: {e}")
        return []

def generate_smart_npc_reply(npc_name, npc_settings, post_content, character_name):
    """基于NPC配置生成智能回复"""
    try:
        # 构建AI提示词
        language_style = npc_settings.get('language_style', 'casual')
        relationship = npc_settings.get('relationship', 'friend')
        example_output = npc_settings.get('example_output', '')
        other_settings = npc_settings.get('other_settings', '')
        
        # 语言风格映射
        style_descriptions = {
            'formal': '正式、礼貌、得体',
            'casual': '随意、轻松、日常',
            'friendly': '友好、温暖、亲切',
            'professional': '专业、严谨、有见地',
            'humorous': '幽默、有趣、轻松',
            'serious': '严肃、认真、深思熟虑'
        }
        
        # 关系映射
        relationship_descriptions = {
            'friend': '朋友关系，可以开玩笑、分享感受',
            'colleague': '同事关系，保持专业但友好',
            'family': '家人关系，关心、温暖、支持',
            'stranger': '陌生人关系，礼貌、适度',
            'student': '学生关系，学习、请教、尊重'
        }
        
        prompt = f"""
你是一个名为"{npc_name}"的NPC，正在回复"{character_name}"的社交动态。

NPC设定：
- 语言风格：{style_descriptions.get(language_style, '随意')}
- 与{character_name}的关系：{relationship_descriptions.get(relationship, '朋友')}
- 示例回复风格：{example_output if example_output else '根据语言风格和关系自然回复'}
- 其他要求：{other_settings if other_settings else '无特殊要求'}

{character_name}的动态内容：
{post_content}

请根据你的NPC设定，生成一条符合你性格和关系的回复。要求：
1. 回复要自然、真实，符合你的语言风格
2. 体现你与{character_name}的关系
3. 回复长度适中,20字以内
4. 可以表达共鸣、关心、建议等情感
5. 不要过于复杂或冗长
6. 此次输出按一句或者一段话话，正常标点符号，不需要加反斜线
7. 如果人物比较活泼，可以适当跟据氛围加入emoji如😥🤣👂👍👎👊👏👌👍👎👊👏👌

直接输出回复内容，不需要引号或其他格式。
"""
        
        # 根据配置选择论坛自定义模型或主模型
        try:
            config = _parse_config()
            use_forum_custom = bool(config.get('ENABLE_FORUM_CUSTOM_MODEL', False))

            if use_forum_custom:
                api_key = (config.get('FORUM_API_KEY') or config.get('DEEPSEEK_API_KEY', '')).strip()
                base_url = config.get('FORUM_BASE_URL', config.get('DEEPSEEK_BASE_URL', 'https://vg.v1api.cc/v1'))
                model = (config.get('FORUM_MODEL') or config.get('MODEL', 'deepseek-v3-0324'))
                temperature = config.get('FORUM_TEMPERATURE', config.get('TEMPERATURE', 1.1))
                max_tokens = config.get('FORUM_MAX_TOKEN', config.get('MAX_TOKEN', 2000))
            else:
                api_key = config.get('DEEPSEEK_API_KEY', '')
                base_url = config.get('DEEPSEEK_BASE_URL', 'https://vg.v1api.cc/v1')
                model = config.get('MODEL', 'deepseek-v3-0324')
                temperature = config.get('TEMPERATURE', 1.1)
                max_tokens = config.get('MAX_TOKEN', 2000)
        except Exception as e:
            current_app.logger.error(f"获取模型配置失败: {e}")
            return generate_fallback_reply(npc_name, language_style, relationship)
        
        if not api_key:
            current_app.logger.warning(f"API密钥未配置，使用默认回复")
            return generate_fallback_reply(npc_name, language_style, relationship)
        
        client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=30  # 提高超时阈值，减少长尾超时
        )
        
        completion = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": prompt
            }],
            temperature=temperature,
            max_tokens=min(max_tokens, 120),  # 按20字回复需求收紧，降低超时概率
            timeout=30
        )
        
        reply = completion.choices[0].message.content.strip()
        
        # 清理回复内容
        if reply and len(reply) > 3:
            # 移除可能的格式标记
            reply = reply.replace('"', '').replace('"', '').replace(''', '').replace(''', '')
            reply = reply.replace('回复：', '').replace('回复:', '').replace('NPC回复：', '').replace('NPC回复:', '')
            
            # 自动替换反斜线为换行符
            reply = reply.replace("\\", "\n")
            
            reply = reply.strip()
            
            if len(reply) > 3:
                return reply
        
        # 如果AI回复失败，使用备用回复
        return generate_fallback_reply(npc_name, language_style, relationship)
        
    except Exception as e:
        current_app.logger.error(f"生成智能NPC回复失败: {e}")
        return generate_fallback_reply(npc_name, 'casual', 'friend')

def generate_fallback_reply(npc_name, language_style, relationship):
    """生成备用回复（当AI调用失败时使用）"""
    try:
        # 基于语言风格和关系的备用回复模板
        fallback_templates = {
            'formal': {
                'friend': ['确实如此', '我理解你的感受', '说得很有道理'],
                'colleague': ['这个观点不错', '值得思考', '有见地'],
                'family': ['我支持你', '相信你能行', '为你感到骄傲'],
                'stranger': ['很有意思', '谢谢分享', '学到了'],
                'mentor': ['很好的想法', '继续努力', '保持这种状态'],
                'student': ['学到了', '谢谢指导', '我会努力的']
            },
            'casual': {
                'friend': ['哈哈哈哈哈', '这个我懂', '真实', '好可爱wwww'],
                'colleague': ['赞同', '同感+1', '确实如此', '支持'],
                'family': ['加油鸭', '支持！', '理解理解', '这就是你'],
                'stranger': ['有意思', '谢谢分享', '学到了', '不错'],
                'mentor': ['很好', '继续', '保持', '不错'],
                'student': ['谢谢', '学到了', '好的', '明白']
            },
            'friendly': {
                'friend': ['好可爱wwww', '理解理解', '加油鸭', '支持！'],
                'colleague': ['赞同', '同感+1', '确实如此', '支持'],
                'family': ['我支持你', '相信你能行', '为你感到骄傲'],
                'stranger': ['很有意思', '谢谢分享', '学到了'],
                'mentor': ['很好的想法', '继续努力', '保持这种状态'],
                'student': ['学到了', '谢谢指导', '我会努力的']
            }
        }
        
        # 获取对应的模板
        templates = fallback_templates.get(language_style, fallback_templates['casual'])
        relationship_templates = templates.get(relationship, templates['friend'])
        
        # 随机选择回复
        return random.choice(relationship_templates)
        
    except Exception as e:
        current_app.logger.error(f"生成备用回复失败: {e}")
        return "赞同"



def load_npc_config():
    """从配置文件加载NPC配置"""
    try:
        npc_config_file = _npc_config_file_path()
        
        if not os.path.exists(npc_config_file):
            current_app.logger.info("NPC配置文件不存在")
            return None
        
        with open(npc_config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        # 确保配置格式完整
        if 'selected_npcs' not in config_data:
            config_data['selected_npcs'] = []
        if 'npc_settings' not in config_data:
            config_data['npc_settings'] = {}
        
        # 为每个选中的NPC确保有默认设置
        for npc_name in config_data.get('selected_npcs', []):
            if npc_name not in config_data.get('npc_settings', {}):
                config_data['npc_settings'][npc_name] = {
                    'language_style': 'casual',
                    'relationship': 'friend',
                    'example_output': '',
                    'other_settings': ''
                }
                current_app.logger.info(f"为NPC {npc_name} 添加默认设置")
            else:
                current_app.logger.info(f"NPC {npc_name} 保持原有设置")
        
        current_app.logger.info(f"成功加载NPC配置: {config_data}")
        return config_data
        
    except Exception as e:
        current_app.logger.error(f"加载NPC配置失败: {e}")
        return None


def delete_forum_post_by_id(character_name, post_id):
    """根据ID删除角色的论坛帖子"""
    try:
        forum_file = _forum_file_path(character_name)
        
        if not os.path.exists(forum_file):
            current_app.logger.warning(f"论坛数据文件不存在: {forum_file}")
            return False
        
        # 读取现有数据
        with open(forum_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        posts = data.get('posts', [])
        
        # 查找并删除指定ID的帖子
        original_count = len(posts)
        posts = [post for post in posts if post.get('id') != post_id]
        
        if len(posts) == original_count:
            current_app.logger.warning(f"未找到要删除的帖子: {post_id}")
            return False
        
        # 更新数据
        data['posts'] = posts
        
        # 保存数据
        with open(forum_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        current_app.logger.info(f"成功删除帖子 {post_id}，剩余帖子数量: {len(posts)}")
        return True
        
    except Exception as e:
        current_app.logger.error(f"删除论坛帖子失败: {e}")
        return False

