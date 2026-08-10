"""规则配置加载模块。

负责读取、缓存和保存 rules_config.json 配置文件。
支持文件变更自动重载，使用模块级缓存提升性能。
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from app.schemas import RuleConfig

logger = logging.getLogger(__name__)

# ---- 模块级缓存 ----
_config_cache: Optional[Dict[str, Any]] = None  # 当前内存中的配置字典
_config_mtime: float = 0.0                      # 上次加载时配置文件的修改时间

# 配置文件路径（与本模块同目录）
_CONFIG_PATH: str = os.path.join(os.path.dirname(__file__), "rules_config.json")


def load_rule_config() -> dict:
    """从磁盘读取 rules_config.json，用 Pydantic 校验后返回配置字典。

    Returns:
        dict: 经过校验的规则配置。

    Raises:
        FileNotFoundError: 配置文件不存在。
        ValidationError:   配置内容不符合 Schema。
    """
    global _config_cache, _config_mtime
    logger.info("正在加载规则配置文件: %s", _CONFIG_PATH)

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        raw: dict = json.load(f)

    # 使用 Pydantic 模型校验
    validated = RuleConfig.model_validate(raw)
    # 将校验后的对象转回 dict（使用 by_alias 保证 global 字段名正确）
    _config_cache = validated.model_dump(by_alias=True)
    _config_mtime = os.path.getmtime(_CONFIG_PATH)
    logger.info("规则配置加载成功，共 %d 张表规则", len(_config_cache.get("tables", [])))
    return _config_cache


def get_rule_config() -> dict:
    """获取当前内存中的配置；若配置文件已被修改（mtime 变化）则自动重载。

    Returns:
        dict: 当前有效的规则配置。
    """
    global _config_cache, _config_mtime

    if _config_cache is None:
        # 首次访问，强制加载
        return load_rule_config()

    current_mtime = os.path.getmtime(_CONFIG_PATH)
    if current_mtime != _config_mtime:
        logger.info("检测到配置文件变更，自动重载")
        return load_rule_config()

    return _config_cache


def save_rule_config(config: dict) -> dict:
    """将配置保存到 JSON 文件并刷新内存缓存。

    Args:
        config: 要保存的规则配置字典。

    Returns:
        dict: 保存后重新加载的配置。
    """
    global _config_cache, _config_mtime
    logger.info("正在保存规则配置到: %s", _CONFIG_PATH)

    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # 刷新缓存
    _config_mtime = os.path.getmtime(_CONFIG_PATH)
    _config_cache = config
    logger.info("规则配置保存成功")
    return _config_cache
