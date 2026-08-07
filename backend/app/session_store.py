"""内存会话存储：dict {session_id: DataFrame}，TTL 30 分钟、上限 10 个、超限淘汰最旧。

进程重启即失效（设计如此，仅当次分析、不持久化）。
"""
import threading
import time
import uuid
from typing import Dict, Optional

import pandas as pd

from . import config


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


# 全局单例
store = SessionStore()
