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


    def _get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话字典，过期时自动清理并返回 None（内部使用，调用方需已持有锁）。"""
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        if time.time() - entry["created_at"] > self.ttl_seconds:
            del self._sessions[session_id]
            return None
        return entry

    def put_chat_message(self, session_id: str, role: str, content: str) -> None:
        """追加一条对话消息到会话历史。"""
        with self._lock:
            session = self._get_session(session_id)
            if session is None:
                return
            if "chat_history" not in session:
                session["chat_history"] = []
            session["chat_history"].append({"role": role, "content": content, "ts": time.time()})
            # FIFO 淘汰：最多保留 20 条消息（10 轮对话）
            if len(session["chat_history"]) > 20:
                session["chat_history"] = session["chat_history"][-20:]
            logger.debug("chat message appended: session=%s, role=%s, history_len=%d",
                         session_id, role, len(session["chat_history"]))

    def get_chat_history(self, session_id: str) -> list:
        """获取会话的对话历史。"""
        with self._lock:
            session = self._get_session(session_id)
            if session is None:
                return []
            return session.get("chat_history", [])

    def clear_chat(self, session_id: str) -> None:
        """清空会话的对话历史。"""
        with self._lock:
            session = self._get_session(session_id)
            if session is None:
                return
            session["chat_history"] = []
            logger.info("chat history cleared: session=%s", session_id)

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
    """多模板提示词存储：支持多个提示词模板的 CRUD 管理。"""

    USER_PROMPT_FILE = Path(__file__).resolve().parent / "user_prompt.json"

    def __init__(self) -> None:
        self._templates: dict[str, dict] = {}  # id -> {name, content}
        self._active_id: str = "default"
        self._load()

    def _load(self) -> None:
        """从 JSON 文件加载模板，失败则创建默认模板。"""
        if self.USER_PROMPT_FILE.exists():
            try:
                data = json.loads(self.USER_PROMPT_FILE.read_text(encoding="utf-8"))
                templates_list = data.get("templates", [])
                self._active_id = data.get("active_id", "default")
                for t in templates_list:
                    self._templates[t["id"]] = {"name": t["name"], "content": t["content"]}
                if not self._templates:
                    self._create_default()
                logger.info("从 user_prompt.json 加载 %d 个模板", len(self._templates))
                return
            except Exception as exc:
                logger.warning("读取 user_prompt.json 失败: %s", exc)
        self._create_default()

    def _create_default(self) -> None:
        """创建默认模板（从 prompts.py 加载默认提示词）。"""
        self._templates = {
            "default": {"name": "默认模板", "content": self._load_from_source()}
        }
        self._active_id = "default"
        self._save_to_json()
        logger.info("已创建默认模板")

    def _save_to_json(self) -> None:
        """保存所有模板到 JSON 文件。"""
        templates_list = [
            {"id": tid, "name": t["name"], "content": t["content"]}
            for tid, t in self._templates.items()
        ]
        data = {"templates": templates_list, "active_id": self._active_id}
        self.USER_PROMPT_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_from_source(self) -> str:
        """从 prompts.py 加载默认提示词。"""
        try:
            from .prompts import DEFAULT_PROMPT
            return DEFAULT_PROMPT
        except Exception as exc:
            logger.warning("从 prompts.py 加载默认提示词失败: %s", exc)
            return ""

    # ---- 模板 CRUD ----

    def list_templates(self) -> list:
        """返回所有模板列表 [{id, name, active}, ...]。"""
        return [
            {"id": tid, "name": t["name"], "active": tid == self._active_id}
            for tid, t in self._templates.items()
        ]

    def get_template(self, template_id: str) -> dict | None:
        """获取单个模板 {id, name, content}，不存在返回 None。"""
        t = self._templates.get(template_id)
        if t is None:
            return None
        return {"id": template_id, "name": t["name"], "content": t["content"]}

    def create_template(self, name: str, content: str) -> dict:
        """创建新模板，返回 {id, name, content}。"""
        import uuid
        tid = uuid.uuid4().hex[:8]
        self._templates[tid] = {"name": name, "content": content}
        self._save_to_json()
        return {"id": tid, "name": name, "content": content}

    def update_template(self, template_id: str, name: str | None = None, content: str | None = None) -> dict | None:
        """更新模板，返回更新后的模板或 None。"""
        t = self._templates.get(template_id)
        if t is None:
            return None
        if name is not None:
            t["name"] = name
        if content is not None:
            t["content"] = content
        self._save_to_json()
        return {"id": template_id, "name": t["name"], "content": t["content"]}

    def delete_template(self, template_id: str) -> bool:
        """删除模板，不允许删除最后一个模板。返回是否成功。"""
        if template_id not in self._templates:
            return False
        if len(self._templates) <= 1:
            return False
        del self._templates[template_id]
        if self._active_id == template_id:
            self._active_id = next(iter(self._templates))
        self._save_to_json()
        return True

    def get_active_template(self) -> dict | None:
        """获取当前激活的模板。"""
        return self.get_template(self._active_id)

    def set_active(self, template_id: str) -> bool:
        """设置当前激活的模板。"""
        if template_id not in self._templates:
            return False
        self._active_id = template_id
        self._save_to_json()
        return True

    # ---- 向后兼容方法 ----

    def save(self, key: str, prompt_text: str) -> None:
        """保存提示词（向后兼容）：保存到当前激活模板。"""
        t = self._templates.get(self._active_id)
        if t:
            t["content"] = prompt_text
            self._save_to_json()

    def get(self, key: str) -> str:
        """获取提示词（向后兼容）：返回当前激活模板的内容。"""
        t = self._templates.get(self._active_id)
        if t:
            return t["content"]
        return self._load_from_source()


# 全局单例
store = SessionStore()

# 全局 PromptStore 单例
prompt_store = PromptStore()
