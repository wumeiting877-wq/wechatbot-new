# -*- coding: utf-8 -*-
"""兼容 shim：把结构化配置暴露为模块级变量。

真实配置在 config.local.json，密钥在 .env。
本文件可以入库，不得写入真实 API Key。
"""

import sys

from app_config import apply_to_module, ensure_example_files, load_config

ensure_example_files()
_cfg = load_config()
apply_to_module(sys.modules[__name__], _cfg)

# 显式导出，便于 from config import *
__all__ = sorted(_cfg.keys())
