# -*- coding: utf-8 -*-
"""统一日志配置：控制台 + 文件双输出，便于后台监控与问题排查。

日志文件：backend/logs/app.log（滚动切割 5MB x 5 个）。
启动时自动清理超过 3 天的历史日志文件（满足"日志只保留最近3天"要求）。
"""
import logging
import os
import time
from logging.handlers import RotatingFileHandler

# 日志保留天数（超过即删除）
RETENTION_DAYS = 3
# 日志目录：backend/logs
_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _cleanup_expired_logs(log_dir: str) -> None:
    """删除目录下修改时间超过 RETENTION_DAYS 天的 *.log* 文件。"""
    cutoff = time.time() - RETENTION_DAYS * 86400
    try:
        for name in os.listdir(log_dir):
            # 仅清理日志文件（app.log / app.log.1 等滚动备份）
            if not name.startswith("app.log"):
                continue
            path = os.path.join(log_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                # 单个文件清理失败不影响整体
                continue
    except OSError:
        pass


def setup_logging() -> None:
    """初始化 root logger（幂等，重复调用不会叠加 handler）。"""
    root = logging.getLogger()
    if getattr(root, "_anomaly_configured", False):
        return

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件输出（滚动切割）
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        _cleanup_expired_logs(_LOG_DIR)
        file_handler = RotatingFileHandler(
            os.path.join(_LOG_DIR, "app.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        # 日志目录不可写时退化为仅控制台输出，不影响服务启动
        root.warning("日志目录不可写，仅输出到控制台: %s", _LOG_DIR)

    root._anomaly_configured = True
    logging.getLogger(__name__).info("日志初始化完成，日志目录: %s", _LOG_DIR)
