# -*- coding: utf-8 -*-
"""AI 对话问答路由：基于上传数据的多轮对话。

- POST /chat/stream   SSE 流式对话
- POST /chat/clear    清空对话历史

通过 import 复用 anomaly_llm.py 中的函数，不修改任何现有文件。
"""
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..session_store import store
from .anomaly_llm import (
    _build_csv,
    _get_llm_config,
    _sse,
    _resolve_months,
    LLM_TIMEOUT_SECONDS,
    CONFIG_MISSING_MSG,
)

logger = logging.getLogger("chat_llm")
router = APIRouter()


class ChatStreamRequest(BaseModel):
    """POST /chat/stream 请求体。"""
    session_id: str
    message: str
    start_month: Optional[str] = None
    end_month: Optional[str] = None


class ChatClearRequest(BaseModel):
    """POST /chat/clear 请求体。"""
    session_id: str


CHAT_SYSTEM_PROMPT = """你是一个专业的保险数据分析助手。用户已上传了保费与保单数据，你需要基于这些数据回答用户的问题。

## 数据处理铁律
1. 忠实原文：仅使用用户提供的数据回答，绝不编造或推测数据。
2. 数值引用：数据末尾的"--- 汇总 ---"行中的 TOTAL 是系统预计算的精确汇总值，引用总数时必须直接使用该行的数值，禁止自行重新累加。
3. 分组计算：对于分组汇总（如按季度、按客户），可以自行计算，但必须展示参与计算的原始数值。
4. 数据缺失：若数据不足以回答问题，明确告知用户"数据不足，无法回答"。

## 回答风格
- 简洁专业，直接给出结论
- 涉及数据时使用 Markdown 表格呈现
- 数值保留合理小数位（默认2位）
"""


@router.post("/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    """SSE 流式对话。"""
    df = store.get(req.session_id)
    if df is None:
        return StreamingResponse(
            iter([_sse({"type": "error", "message": "会话已过期，请重新上传文件"})]),
            media_type="text/event-stream",
        )

    cfg = _get_llm_config()
    if not cfg:
        return StreamingResponse(
            iter([_sse({"type": "error", "message": CONFIG_MISSING_MSG})]),
            media_type="text/event-stream",
        )
    logger.info("Chat LLM 调用: model=%s, base_url=%s", cfg["model"], cfg["base_url"])

    months = _resolve_months(req.start_month, req.end_month)
    csv_text, _ = _build_csv(df, months, session_id=req.session_id)

    history = store.get_chat_history(req.session_id)
    is_first_turn = len(history) == 0

    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]

    if is_first_turn:
        messages.append({
            "role": "user",
            "content": "以下是数据：\n```csv\n" + csv_text + "\n```\n\n用户问题：" + req.message,
        })
    else:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": req.message})

    store.put_chat_message(req.session_id, "user", req.message)

    async def event_generator():
        full_reply = ""
        try:
            payload = {
                "model": cfg["model"],
                "messages": messages,
                "stream": True,
                "temperature": 0.2,
                "max_tokens": cfg["max_tokens"],
            }
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
                async with client.stream(
                    "POST",
                    f"{cfg['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            delta_content = delta.get("content", "")
                            if delta_content:
                                full_reply += delta_content
                                yield _sse({"type": "delta", "content": delta_content})
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        except Exception as e:
            logger.exception("LLM 调用异常")
            yield _sse({"type": "error", "message": "服务异常: " + str(e)})
            return

        store.put_chat_message(req.session_id, "assistant", full_reply)
        yield _sse({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat/clear")
async def chat_clear(req: ChatClearRequest):
    """清空对话历史。"""
    store.clear_chat(req.session_id)
    return {"ok": True}
