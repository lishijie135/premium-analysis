# -*- coding: utf-8 -*-
"""AI 对话问答路由：基于上传数据的多轮对话（Code Interpreter Agent 模式）。

- POST /chat/stream   SSE 流式对话（两阶段：代码生成 → 结果解读）
- POST /chat/clear    清空对话历史

通过 import 复用 anomaly_llm.py 中的辅助函数。
"""
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..session_store import store
from ..prompts import CODE_GEN_SYSTEM_PROMPT
from ..code_executor import execute_analysis_code
from .anomaly_llm import (
    _get_llm_config,
    _sse,
    _resolve_months,
    _build_schema_info,
    _build_sample_data,
    _extract_code_from_response,
    _call_llm_non_streaming,
    _prepare_cleaned_df,
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


CHAT_SYSTEM_PROMPT = """你是一个专业的保险数据分析助手。用户已上传了保费与保单数据，系统已通过代码精确计算并返回了结果。

## 核心原则
1. 忠实结果：所有数据引用必须基于代码执行结果，禁止编造或修改任何数值。
2. 数据缺失：若代码执行结果不足以回答问题，明确告知用户"数据不足，无法回答"。
3. 如果结果中包含校验信息（validation），可注明数据已通过交叉验证。

## 回答风格
- 简洁专业，直接给出结论
- 涉及数据时使用 Markdown 表格呈现
- 数值保留合理小数位（默认2位）
"""


@router.post("/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    """SSE 流式对话（Code Interpreter Agent 两阶段模式）。"""
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
    logger.info("Chat Agent 调用: model=%s, base_url=%s", cfg["model"], cfg["base_url"])

    # 数据准备：清洗 + 月份过滤
    months = _resolve_months(req.start_month, req.end_month)
    try:
        filtered_df, precomputed_stats = _prepare_cleaned_df(
            df, months, session_id=req.session_id,
        )
    except ValueError as exc:
        logger.error("Chat 数据准备失败: %s", exc)
        return StreamingResponse(
            iter([_sse({"type": "error", "message": str(exc)})]),
            media_type="text/event-stream",
        )

    # 构建 Schema 和样本数据
    schema_info = _build_schema_info(filtered_df)
    sample_data = _build_sample_data(filtered_df, n=5)
    row_count = len(filtered_df)

    code_gen_system = CODE_GEN_SYSTEM_PROMPT.format(
        schema=schema_info,
        row_count=row_count,
        sample=sample_data,
    )

    # 获取对话历史
    history = store.get_chat_history(req.session_id)

    # 记录用户消息
    store.put_chat_message(req.session_id, "user", req.message)

    async def event_generator():
        full_reply = ""

        # ------------------------------------------------------------------
        # 阶段一-A：代码生成（非流式 LLM 调用）
        # ------------------------------------------------------------------
        yield _sse({"type": "executing", "message": "正在生成分析代码..."})

        # 构建代码生成消息
        code_user_content = req.message
        if history:
            # 多轮对话时，附带上一轮的上下文
            last_history = history[-1] if history else None
            if last_history and last_history["role"] == "assistant":
                code_user_content = f"用户问题：{req.message}\n\n（这是多轮对话的后续问题，请基于数据结构生成合适的分析代码）"

        code_messages = [
            {"role": "system", "content": code_gen_system},
            {"role": "user", "content": code_user_content},
        ]

        max_retries = 2
        final_code = ""
        final_exec_result = None

        for attempt in range(max_retries + 1):
            try:
                llm_response = await _call_llm_non_streaming(cfg, code_messages)
                extracted_code = _extract_code_from_response(llm_response)
                final_code = extracted_code

                yield _sse({"type": "code", "content": extracted_code})
                logger.info(
                    "Chat Agent 代码生成完成: attempt=%d, code_len=%d",
                    attempt + 1, len(extracted_code),
                )
            except Exception as exc:
                logger.exception("Chat 代码生成阶段 LLM 调用失败: %s", exc)
                yield _sse({"type": "error", "message": f"代码生成失败: {exc}"})
                return

            # ------------------------------------------------------------------
            # 本地执行代码
            # ------------------------------------------------------------------
            yield _sse({"type": "executing", "message": "正在计算..."})

            exec_result = execute_analysis_code(
                extracted_code, filtered_df, precomputed_stats,
            )
            final_exec_result = exec_result

            yield _sse({"type": "result", "content": json.dumps(exec_result, ensure_ascii=False)})

            if exec_result["success"]:
                logger.info("Chat 代码执行成功")
                break
            else:
                error_msg = exec_result.get("error", "未知错误")
                logger.warning(
                    "Chat 代码执行失败 (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, error_msg,
                )
                if attempt < max_retries:
                    yield _sse({"type": "executing", "message": f"代码执行出错，正在修正重试 ({attempt + 1}/{max_retries})..."})
                    code_messages.append({"role": "assistant", "content": llm_response})
                    code_messages.append({
                        "role": "user",
                        "content": f"代码执行出错：{error_msg}\n请修正代码并重新输出完整的 Python 代码。",
                    })

        # ------------------------------------------------------------------
        # 阶段一-B：结果解读（流式 LLM 调用）
        # ------------------------------------------------------------------
        if final_exec_result and final_exec_result["success"]:
            result_json = json.dumps(final_exec_result["result"], ensure_ascii=False, indent=2)
            validation_note = ""
            if final_exec_result.get("validation", {}).get("warnings"):
                validation_note = "\n\n⚠️ 数据校验告警：\n" + "\n".join(
                    f"- {w}" for w in final_exec_result["validation"]["warnings"]
                )
            interpret_user_msg = (
                f"用户问题：{req.message}\n\n"
                f"以下是代码执行的精确计算结果：\n```json\n{result_json}\n```"
                f"{validation_note}\n\n请基于上述结果回答用户的问题。"
            )
        else:
            error_info = final_exec_result.get("error", "代码执行失败") if final_exec_result else "代码执行异常"
            interpret_user_msg = (
                f"用户问题：{req.message}\n\n"
                f"数据分析代码执行失败，错误信息：{error_info}\n\n"
                f"请如实告知用户代码执行遇到了问题。"
            )

        interpret_messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": interpret_user_msg},
        ]

        # 流式调用 LLM
        try:
            payload = {
                "model": cfg["model"],
                "messages": interpret_messages,
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
            logger.exception("Chat 阶段二 LLM 调用异常")
            yield _sse({"type": "error", "message": "服务异常: " + str(e)})
            return

        # 存储助手回复（仅存储最终解读文本）
        store.put_chat_message(req.session_id, "assistant", full_reply)
        yield _sse({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat/clear")
async def chat_clear(req: ChatClearRequest):
    """清空对话历史。"""
    store.clear_chat(req.session_id)
    return {"ok": True}
