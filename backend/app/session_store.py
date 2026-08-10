from __future__ import annotations
"""内存会话存储：dict {session_id: DataFrame}，TTL 12 小时、上限 10 个、超限淘汰最旧。

进程重启即失效（设计如此，仅当次分析、不持久化）。
"""
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from . import config

logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(
        self,
        ttl_seconds: int = config.SESSION_TTL_SECONDS,
        max_sessions: int = config.MAX_SESSIONS,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def put(self, df: pd.DataFrame) -> str:
        with self._lock:
            self._purge_expired_locked()
            while len(self._sessions) >= self.max_sessions:
                oldest = min(
                    self._sessions.items(), key=lambda kv: kv[1]["created_at"]
                )[0]
                del self._sessions[oldest]
            session_id = uuid.uuid4().hex
            self._sessions[session_id] = {"df": df, "created_at": time.time()}
            return session_id

    def get(self, session_id: str) -> Optional[pd.DataFrame]:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            if time.time() - entry["created_at"] > self.ttl_seconds:
                del self._sessions[session_id]
                return None
            return entry["df"]

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def put_mapping(self, session_id: str, mapping: dict) -> None:
        """保存用户确认的列映射到会话中，供 AI 分析复用。"""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                entry["mapping"] = mapping
                logger.info("已保存用户确认的 mapping: session=%s, mapping=%s", session_id, mapping)

    def get_mapping(self, session_id: str) -> Optional[dict]:
        """获取用户确认的列映射，不存在时返回 None。"""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            if time.time() - entry["created_at"] > self.ttl_seconds:
                del self._sessions[session_id]
                return None
            return entry.get("mapping")

    def size(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, e in self._sessions.items()
            if now - e["created_at"] > self.ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]


# ---------------------------------------------------------------------------
# PromptStore：用户提示词持久化存储
# 将用户保存的提示词写入 JSON 文件（user_prompt.json），而非 prompts.py 源文件，
# 避免部署时 Git 覆盖导致用户自定义提示词丢失。
# ---------------------------------------------------------------------------
class PromptStore:
    """用户提示词存储：优先从 JSON 文件加载，回退到 prompts.py 默认值。"""

    USER_PROMPT_FILE = Path(__file__).resolve().parent / "user_prompt.json"

    def __init__(self) -> None:
        self._prompts: dict[str, str] = {}
        # 优先从 JSON 文件加载用户保存的提示词
        user_prompt = self._load_from_json()
        if user_prompt:
            self._prompts["default"] = user_prompt
            logger.info("从 user_prompt.json 加载用户提示词成功（%d 字符）", len(user_prompt))
        else:
            # 回退到 prompts.py 中的默认值
            self._prompts["default"] = self._load_from_source()
            logger.info("user_prompt.json 不存在，使用 prompts.py 默认提示词")

    def _load_from_json(self) -> str | None:
        """从 user_prompt.json 加载用户保存的提示词。"""
        if self.USER_PROMPT_FILE.exists():
            try:
                data = json.loads(self.USER_PROMPT_FILE.read_text(encoding="utf-8"))
                return data.get("prompt")
            except Exception as exc:
                logger.warning("读取 user_prompt.json 失败: %s，将回退到默认提示词", exc)
                return None
        return None

    def _save_to_json(self, prompt_text: str) -> None:
        """将用户提示词保存到 JSON 文件（不被 Git 跟踪）。"""
        self.USER_PROMPT_FILE.write_text(
            json.dumps({"prompt": prompt_text}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("用户提示词已保存到 %s（%d 字符）", self.USER_PROMPT_FILE, len(prompt_text))

    def _load_from_source(self) -> str:
        """从 prompts.py 加载默认提示词（保留原有逻辑）。"""
        try:
            from .prompts import DEFAULT_PROMPT
            return DEFAULT_PROMPT
        except Exception as exc:
            logger.warning("从 prompts.py 加载默认提示词失败: %s", exc)
            return ""

    def save(self, key: str, prompt_text: str) -> None:
        """保存提示词到内存和 JSON 文件。"""
        self._prompts[key] = prompt_text
        self._save_to_json(prompt_text)

    def get(self, key: str) -> str:
        """获取提示词，不存在时回退到 prompts.py 默认值。"""
        return self._prompts.get(key, self._load_from_source())


# 全局单例
store = SessionStore()

# 全局 PromptStore 单例
prompt_store = PromptStore()
