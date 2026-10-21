# -*- coding: utf-8 -*-
"""文件读写：自动处理编码，避免散落在 bot.py 里。"""

from __future__ import annotations

import logging
import os
import shutil
import time

logger = logging.getLogger(__name__)


def safe_read_file_with_encoding(file_path, fallback_content=""):
    """
    安全地读取文件，自动处理编码问题。

    Args:
        file_path (str): 文件路径
        fallback_content (str): 如果所有编码都失败时返回的内容

    Returns:
        str: 文件内容
    """
    encodings_to_try = ['utf-8', 'gbk', 'gb2312', 'latin-1', 'cp1252']

    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()

            if encoding != 'utf-8':
                logger.info(f"文件 {file_path} 使用 {encoding} 编码读取成功，正在转换为UTF-8")
                backup_path = f"{file_path}.bak_{int(time.time())}"
                try:
                    shutil.copy(file_path, backup_path)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"已将文件转换为UTF-8编码: {file_path} (备份: {backup_path})")
                except Exception as save_err:
                    logger.error(f"转换文件编码失败: {save_err}")

            return content

        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.error(f"读取文件时发生错误: {file_path}, 编码: {encoding}, 错误: {e}")
            continue

    logger.error(f"所有编码格式都无法读取文件: {file_path}")
    backup_path = f"{file_path}.corrupted_{int(time.time())}"
    try:
        shutil.copy(file_path, backup_path)
        logger.error(f"已备份损坏文件到: {backup_path}")
    except Exception as backup_err:
        logger.error(f"备份损坏文件失败: {backup_err}")

    return fallback_content


def safe_write_file_with_encoding(file_path, content, mode='w'):
    """
    安全地写入文件，自动处理编码问题。

    Args:
        file_path (str): 文件路径
        content (str): 要写入的内容
        mode (str): 写入模式，'w' 或 'a'
    """
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(file_path, mode, encoding='utf-8') as f:
            f.write(content)
    except UnicodeEncodeError as e:
        logger.warning(f"UTF-8编码失败，清理特殊字符: {file_path}, 错误: {e}")
        clean_content = content.encode('utf-8', errors='ignore').decode('utf-8')
        with open(file_path, mode, encoding='utf-8') as f:
            f.write(clean_content)
        logger.info(f"已清理特殊字符并写入文件: {file_path}")
