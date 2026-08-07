"""客户业绩保费分析系统 后端入口。

启动：python -m uvicorn app.main:app --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .logging_setup import setup_logging
from .routers import analyze as analyze_router
from .routers import anomaly_llm as anomaly_llm_router

# 初始化统一日志（控制台 + logs/app.log，仅保留最近3天）
setup_logging()

app = FastAPI(title="客户业绩保费分析系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router.router, prefix="/api")
# AI 异常分析（大模型提示词驱动 + SSE 流式输出）
app.include_router(anomaly_llm_router.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
