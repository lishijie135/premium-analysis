"""生产部署入口：在现有 API 应用之上托管前端静态产物。

前端已在本地用 `npm run build` 构建，产物目录由环境变量 DIST_DIR 指定
（默认 ../frontend_dist，即仓库外的构建输出目录）。

启动（在 backend/ 目录下）：
    uvicorn serve:app --host 0.0.0.0 --port 8000

- /api/*        -> 原有 FastAPI 业务接口（analyze / anomaly / chat / health）
- /assets/*     -> 前端打包后的静态资源（js/css）
- 其余 GET 路径  -> 回退到 index.html（SPA 单页应用）
"""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.main import app  # 复用已注册好 /api 路由的 app 实例

DIST_DIR = os.environ.get(
    "DIST_DIR",
    os.path.join(os.path.dirname(__file__), "..", "frontend_dist"),
)
DIST_DIR = os.path.abspath(DIST_DIR)
INDEX = os.path.join(DIST_DIR, "index.html")
ASSETS = os.path.join(DIST_DIR, "assets")


def _mount_static():
    if not os.path.isdir(DIST_DIR):
        print(f"[serve] 警告: 前端产物目录不存在: {DIST_DIR}，仅启动 API 服务")
        return
    if os.path.isdir(ASSETS):
        app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
    if os.path.isfile(INDEX):

        @app.get("/{full_path:path}")
        async def _spa_fallback(full_path: str):
            return FileResponse(INDEX)


_mount_static()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
