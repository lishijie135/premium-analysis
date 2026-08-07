# -*- coding: utf-8 -*-
"""AI 异常分析路由：默认提示词查询 + 大模型 SSE 流式分析。

- GET  /anomaly/default-prompt  返回默认提示词
- POST /anomaly/stream          SSE 流式输出大模型分析结果

SSE 事件格式（每行一个 JSON）：
  data: {"type":"warning","message":"..."}   警告（可选，首事件）
  data: {"type":"delta","content":"..."}     模型输出增量文本
  data: {"type":"done"}                      正常结束
  data: {"type":"error","message":"..."}     错误（配置缺失/模型调用失败等）

模型配置读取 backend/.env（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL），
兼容 .env 不存在或字段缺失：此时 SSE 返回明确的 error 事件，不抛 500。
"""
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import parser
from ..prompts import DEFAULT_PROMPT
from ..session_store import store

logger = logging.getLogger("anomaly_llm")

router = APIRouter()

# 模型请求超时（秒）：完整数据量大时模型耗时较长，预留 1 小时
LLM_TIMEOUT_SECONDS = 3600.0

# backend/.env 路径（本文件位于 backend/app/routers/ 下，向上三级为 backend/）
_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_ENV_PATH = os.path.join(_BACKEND_DIR, ".env")

# 配置缺失时的统一错误提示
CONFIG_MISSING_MSG = "请先在 backend/.env 配置 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL"


class StreamRequest(BaseModel):
    """POST /anomaly/stream 请求体。"""

    session_id: str
    prompt: str  # 用户当前编辑的完整提示词


def _sse(payload: Dict) -> str:
    """构造一条 SSE 事件（data: {...}\\n\\n）。"""
    return "data: %s\n\n" % json.dumps(payload, ensure_ascii=False)


def _parse_dotenv(path: str) -> Dict[str, str]:
    """极简 .env 解析：支持 KEY=VALUE、# 注释、空行；文件不存在返回空 dict。"""
    values: Dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    try:
        # utf-8-sig 兼容带 BOM 的 .env（Windows 记事本/PowerShell 常见）
        with open(path, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                # 去除可选的包裹引号
                values[key.strip()] = val.strip().strip('"').strip("'")
    except OSError as exc:
        logger.warning("读取 .env 失败: %s", exc)
    return values



def _parse_bool(value: str) -> bool:
    """将字符串配置值解析为布尔值：支持 true/false/1/0/yes/no（不区分大小写）。"""
    return value.strip().lower() in ("true", "1", "yes")


def _get_llm_config() -> Optional[Dict[str, str]]:
    """读取模型配置；任一字段缺失返回 None。进程环境变量优先于 .env。"""
    dotenv = _parse_dotenv(_ENV_PATH)
    base_url = (os.environ.get("LLM_BASE_URL") or dotenv.get("LLM_BASE_URL") or "").strip()
    api_key = (os.environ.get("LLM_API_KEY") or dotenv.get("LLM_API_KEY") or "").strip()
    model = (os.environ.get("LLM_MODEL") or dotenv.get("LLM_MODEL") or "").strip()
    if not (base_url and api_key and model):
        return None
    # 读取 enable_thinking 配置（默认 false）
    thinking_raw = (os.environ.get("LLM_ENABLE_THINKING") or dotenv.get("LLM_ENABLE_THINKING") or "false").strip()
    enable_thinking = _parse_bool(thinking_raw)
    # 读取 max_tokens 配置（默认 16384，DashScope qwen-plus 支持的最大输出 token 数）
    max_tokens_raw = (os.environ.get("LLM_MAX_TOKENS") or dotenv.get("LLM_MAX_TOKENS") or "16384").strip()
    try:
        max_tokens = int(max_tokens_raw)
    except (ValueError, TypeError):
        max_tokens = 16384
    return {"base_url": base_url.rstrip("/"), "api_key": api_key, "model": model, "enable_thinking": enable_thinking, "max_tokens": max_tokens}


# ---------------------------------------------------------------------------
# 分析所需月份列表（可根据提示词中的周期定义调整）
# 当前覆盖周期：
#   表1: 26Q1(2026-01/02/03) vs 26Q2(2026-04/05/06)
#   表2: 25Q4(2025-10/11/12) vs 26Q2(2026-04/05/06)
#   表3: 2026-06 vs 2026-07
# 合并去重后共 10 个月份
# ---------------------------------------------------------------------------
REQUIRED_MONTHS: List[Tuple[int, int]] = [
    (2025, 10), (2025, 11), (2025, 12),  # 25Q4
    (2026, 1),  (2026, 2),  (2026, 3),   # 26Q1
    (2026, 4),  (2026, 5),  (2026, 6),   # 26Q2
    (2026, 7),                            # 26Q2+1（表3 对比月）
]

# 月度明细 CSV 字符数上限；超过此值则降级为季度聚合数据
_MONTHLY_CSV_CHAR_LIMIT = 100_000


def _build_csv(df: pd.DataFrame) -> Tuple[str, Optional[str]]:
    """将会话原始数据清洗后构建发送给大模型的 CSV 数据。

    策略（智能降级）：
    1. 先过滤只保留分析所需月份（REQUIRED_MONTHS），大幅减少数据量；
    2. 若过滤后月度明细 CSV 仍超过 _MONTHLY_CSV_CHAR_LIMIT 字符，
       则进一步降级为按 客户×季度 聚合的数据；
    3. 返回 (csv_text, warning_or_None)；无法构建时抛出 ValueError。

    所需月份列表可根据提示词中的周期定义在 REQUIRED_MONTHS 常量处调整。
    """
    columns: List[str] = [str(c) for c in df.columns if str(c) != "__orig_idx__"]
    mapping = parser.auto_map_columns(columns)
    # 自动列识别失败则无法清洗数据
    if any(v is None for v in mapping.values()):
        raise ValueError("无法自动识别数据列（需包含 客户代码/签单时间/保费量/出单量）")

    parsed = parser.extract_records(df, mapping)
    cleaned: pd.DataFrame = parsed["cleaned"]
    if len(cleaned) == 0:
        raise ValueError("会话数据中没有有效明细行，无法进行分析")

    # ---- 第一步：过滤只保留分析所需月份 ----
    required_set = set(REQUIRED_MONTHS)  # {(year, month), ...}
    filtered = cleaned[
        cleaned.apply(lambda r: (r.year, r.month) in required_set, axis=1)
    ].copy()
    if len(filtered) == 0:
        raise ValueError(
            "会话数据中没有分析所需月份（%s）的数据，请检查文件内容"
            % ", ".join("%04d-%02d" % (y, m) for y, m in REQUIRED_MONTHS)
        )

    logger.info(
        "月份过滤: 原始 %d 行 -> 过滤后 %d 行（所需月份 %d 个）",
        len(cleaned), len(filtered), len(required_set),
    )

    # ---- 第二步：构建月度明细 CSV ----
    filtered = filtered.sort_values(["customer", "year", "month"])
    monthly_csv = _df_to_csv(filtered)
    logger.info("月度明细 CSV 字符数: %d（阈值 %d）", len(monthly_csv), _MONTHLY_CSV_CHAR_LIMIT)

    if len(monthly_csv) <= _MONTHLY_CSV_CHAR_LIMIT:
        # 月度明细在阈值内，直接发送
        return monthly_csv, None

    # ---- 第三步：降级为季度聚合 ----
    logger.info(
        "月度明细 CSV（%d 字符）超过阈值（%d），降级为季度聚合数据",
        len(monthly_csv), _MONTHLY_CSV_CHAR_LIMIT,
    )
    quarterly_csv = _build_quarterly_csv(filtered)
    warning = (
        "数据量较大（月度明细 %d 字符），已自动降级为季度聚合数据发送，"
        "分析结果可能受粒度影响" % len(monthly_csv)
    )
    return quarterly_csv, warning


def _df_to_csv(data: pd.DataFrame) -> str:
    """将已排序的 DataFrame 转为标准 CSV 文本（含表头，不含索引）。"""
    lines = ["客户代码,月份,保费,单量"]
    for r in data.itertuples(index=False):
        lines.append(
            "%s,%04d-%02d,%.2f,%d" % (r.customer, r.year, r.month, r.premium, r.policies)
        )
    return "\n".join(lines)


def _month_to_quarter(year: int, month: int) -> str:
    """将年月转换为季度标签，如 (2026, 2) -> '26Q1'。"""
    q = (month - 1) // 3 + 1
    return "%dQ%d" % (year % 100, q)


def _build_quarterly_csv(data: pd.DataFrame) -> str:
    """将月度明细按 客户×季度 聚合求和，生成降级 CSV。

    季度标签格式：25Q4 / 26Q1 / 26Q2 等。
    特殊处理：2026-07 不属于标准季度，归入 '26Q3' 标签以保持数据完整。
    """
    # key: (customer, year, quarter_label) -> (premium_sum, policies_sum)
    agg_rows: Dict[Tuple[str, int, str], Tuple[float, int]] = {}
    for r in data.itertuples(index=False):
        quarter = _month_to_quarter(r.year, r.month)
        key = (r.customer, r.year, quarter)
        prev = agg_rows.get(key, (0.0, 0))
        agg_rows[key] = (prev[0] + r.premium, prev[1] + r.policies)

    # 按 客户代码 -> 年份 -> 季度 排序
    sorted_keys = sorted(agg_rows.keys(), key=lambda k: (k[0], k[1], k[2]))
    lines = ["客户代码,季度,保费,单量"]
    for cust, _yr, qtr in sorted_keys:
        prem, pol = agg_rows[(cust, _yr, qtr)]
        lines.append("%s,%s,%.2f,%d" % (cust, qtr, prem, pol))
    csv_text = "\n".join(lines)
    logger.info("季度聚合 CSV 字符数: %d（%d 行）", len(csv_text), len(sorted_keys))
    return csv_text


@router.get("/anomaly/default-prompt")
def default_prompt():
    """返回默认提示词，供前端编辑区初始化。"""
    return {"prompt": DEFAULT_PROMPT}


@router.post("/anomaly/stream")
async def anomaly_stream(req: StreamRequest):
    """SSE 流式异常分析：聚合数据 + 用户提示词 → 大模型 → 逐块转发。"""
    # 会话不存在（未上传或已过期）→ 404 JSON，前端已有会话过期处理
    df = store.get(req.session_id)
    if df is None:
        logger.info("anomaly/stream 会话不存在或已过期: %s", req.session_id)
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新上传文件")

    async def event_gen():
        # 1. 模型配置检查（缺失时返回明确 error 事件，不 500）
        cfg = _get_llm_config()
        if cfg is None:
            logger.error("LLM 配置缺失，请检查 backend/.env")
            yield _sse({"type": "error", "message": CONFIG_MISSING_MSG})
            return

        # 2. 构建数据 CSV（客户x月份聚合）
        try:
            csv_text, warning = _build_csv(df)
        except ValueError as exc:
            logger.error("构建分析数据失败: %s", exc)
            yield _sse({"type": "error", "message": str(exc)})
            return

        # 数据警告作为首个事件下发（降级时附带说明信息）
        if warning:
            yield _sse({"type": "warning", "message": warning})

        # 3. 组装消息：system=用户提示词（分析规则），user=数据
        messages = [
            {"role": "system", "content": req.prompt or DEFAULT_PROMPT},
            {
                "role": "user",
                "content": "以下是数据：\n```csv\n%s\n```\n请根据规则输出分析结果" % csv_text,
            },
        ]
        payload = {
            "model": cfg["model"],
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
            # DashScope qwen-plus OpenAI 兼容接口：enable_thinking 控制是否开启思考过程
            # 用户可在 backend/.env 中设置 LLM_ENABLE_THINKING=true 来开启
            "enable_thinking": cfg["enable_thinking"],
            "max_tokens": cfg["max_tokens"],
        }
        url = cfg["base_url"] + "/chat/completions"
        headers = {
            "Authorization": "Bearer %s" % cfg["api_key"],
            "Content-Type": "application/json",
        }
        logger.info(
            "开始 LLM 流式分析: session=%s model=%s csv_chars=%d enable_thinking=%s max_tokens=%d",
            req.session_id, cfg["model"], len(csv_text), cfg["enable_thinking"], cfg["max_tokens"],
        )

        # 4. httpx 直连 OpenAI 兼容接口，逐块转发 delta
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS)
            ) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", errors="ignore")
                        logger.error(
                            "模型服务返回异常状态: HTTP %d body=%s",
                            resp.status_code, body[:500],
                        )
                        yield _sse({
                            "type": "error",
                            "message": "模型服务调用失败（HTTP %d）：%s"
                            % (resp.status_code, body[:500]),
                        })
                        return

                    # 解析 OpenAI 兼容 SSE：data: {json} / data: [DONE]
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            logger.warning("跳过无法解析的模型响应行: %s", data[:200])
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield _sse({"type": "delta", "content": content})
            yield _sse({"type": "done"})
            logger.info("LLM 流式分析完成: session=%s", req.session_id)
        except httpx.TimeoutException:
            logger.error("模型请求超时（%ds）: session=%s", int(LLM_TIMEOUT_SECONDS), req.session_id)
            yield _sse({"type": "error", "message": "模型请求超时（%d秒），请稍后重试" % int(LLM_TIMEOUT_SECONDS)})
        except httpx.HTTPError as exc:
            logger.error("模型服务连接失败: %s", exc)
            yield _sse({"type": "error", "message": "模型服务连接失败：%s" % exc})
        except Exception:  # 兜底：任何未预期异常都转为 error 事件，避免连接静默断开
            logger.exception("LLM 流式分析发生未预期异常: session=%s", req.session_id)
            yield _sse({"type": "error", "message": "分析过程发生异常，请稍后重试"})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 等代理缓冲，保证流式实时性
        },
    )
