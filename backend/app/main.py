"""客户业绩保费分析系统 后端入口。

启动：python -m uvicorn app.main:app --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import auth, config
from .logging_setup import setup_logging
from .routers import analyze as analyze_router
from .routers import anomaly_llm as anomaly_llm_router
from .routers import auth as auth_router
from .routers import chat_llm as chat_llm_router

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

# ---- 全局鉴权中间件 ----
# 对所有 /api 接口（登录、公钥下发、健康检查除外）强制校验 Bearer Token，
# 缺失 / 无效 / 过期一律返回 401。静态资源与 SPA 回退（非 /api）不受影响。
AUTH_EXEMPT = {"/api/auth/login", "/api/auth/rsa-public-key", "/api/health"}


@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in AUTH_EXEMPT:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
        if not auth.verify_token(token):
            return JSONResponse(
                status_code=401, content={"detail": "未登录或登录已过期，请重新登录"}
            )
    return await call_next(request)


app.include_router(analyze_router.router, prefix="/api")
# AI 异常分析（大模型提示词驱动 + SSE 流式输出）
app.include_router(anomaly_llm_router.router, prefix="/api")
# AI 智能对话（多轮对话 + SSE 流式输出）
app.include_router(chat_llm_router.router, prefix="/api")
# 认证（路由内已带 /api/auth 前缀，此处不再叠加 /api）
app.include_router(auth_router.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
