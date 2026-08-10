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
import re
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import parser
from ..prompts import DEFAULT_PROMPT
from ..session_store import store, prompt_store

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
    start_month: Optional[str] = None  # "YYYY-MM" 格式，如 "2025-10"
    end_month: Optional[str] = None    # "YYYY-MM" 格式，如 "2026-07"


class SavePromptRequest(BaseModel):
    """POST /anomaly/save-prompt 请求体。"""

    prompt: str  # 用户编辑的提示词内容


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
    # 读取 max_tokens 配置（默认 16384，DashScope qwen3.7-plus 支持的最大输出 token 数）
    max_tokens_raw = (os.environ.get("LLM_MAX_TOKENS") or dotenv.get("LLM_MAX_TOKENS") or "8192").strip()
    try:
        max_tokens = int(max_tokens_raw)
    except (ValueError, TypeError):
        max_tokens = 8192
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



def _resolve_months(start_month: Optional[str], end_month: Optional[str]) -> List[Tuple[int, int]]:
    """根据起止月份生成月份列表。

    - 两者都提供：从 start_month 到 end_month 逐月生成
    - 任一缺失：回退到 REQUIRED_MONTHS（向后兼容）

    参数格式: "YYYY-MM"，如 "2025-10"
    返回: [(year, month), ...] 按时间升序排列
    """
    if not start_month or not end_month:
        # 任一缺失，回退到默认月份列表（向后兼容）
        return list(REQUIRED_MONTHS)

    try:
        # 解析 "YYYY-MM" 格式
        s_parts = start_month.split("-")
        e_parts = end_month.split("-")
        s_year, s_month = int(s_parts[0]), int(s_parts[1])
        e_year, e_month = int(e_parts[0]), int(e_parts[1])
    except (ValueError, IndexError):
        logger.warning("无法解析月份参数: start=%s end=%s，回退到默认", start_month, end_month)
        return list(REQUIRED_MONTHS)

    # 逐月递增生成列表
    months: List[Tuple[int, int]] = []
    year, month = s_year, s_month
    while (year, month) <= (e_year, e_month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1

    if not months:
        logger.warning("生成的月份列表为空（start=%s end=%s），回退到默认", start_month, end_month)
        return list(REQUIRED_MONTHS)

    logger.info("动态月份范围: %s ~ %s，共 %d 个月", start_month, end_month, len(months))
    return months


def _build_csv(df: pd.DataFrame, months: Optional[List[Tuple[int, int]]] = None, session_id: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """将会话原始数据清洗后构建发送给大模型的 CSV 数据。

    始终发送完整月度明细数据给 LLM（不再自动降级为季度聚合）。
    1. 先过滤只保留分析所需月份（REQUIRED_MONTHS），减少无关数据量；
    2. 返回 (csv_text, warning_or_None)；无法构建时抛出 ValueError。
    注：_build_quarterly_csv 降级函数保留作为备用。

    所需月份列表可根据提示词中的周期定义在 REQUIRED_MONTHS 常量处调整。
    """
    columns: List[str] = [str(c) for c in df.columns if str(c) != "__orig_idx__"]

    # 优先使用用户确认的 mapping（保证 AI 分析与业绩分析数据一致），不存在时回退到自动识别
    mapping = None
    if session_id:
        mapping = store.get_mapping(session_id)
        if mapping is not None:
            logger.info("使用用户确认的 mapping: session=%s, mapping=%s", session_id, mapping)
    if mapping is None:
        mapping = parser.auto_map_columns(columns)
        logger.info("未找到用户确认的 mapping，使用自动识别: %s", mapping)

    # 自动列识别失败则无法清洗数据
    if any(v is None for v in mapping.values()):
        raise ValueError("无法自动识别数据列（需包含 客户代码/签单时间/保费量/出单量）")

    parsed = parser.extract_records(df, mapping)
    cleaned: pd.DataFrame = parsed["cleaned"]
    if len(cleaned) == 0:
        raise ValueError("会话数据中没有有效明细行，无法进行分析")

    # ---- 第一步：过滤只保留分析所需月份 ----
    # 使用传入的动态月份列表，若未传入则回退到默认 REQUIRED_MONTHS（向后兼容）
    active_months = months if months is not None else list(REQUIRED_MONTHS)
    required_set = set(active_months)  # {(year, month), ...}
    filtered = cleaned[
        cleaned.apply(lambda r: (r.year, r.month) in required_set, axis=1)
    ].copy()
    if len(filtered) == 0:
        raise ValueError(
            "会话数据中没有分析所需月份（%s）的数据，请检查文件内容"
            % ", ".join("%04d-%02d" % (y, m) for y, m in active_months)
        )

    logger.info(
        "月份过滤: 原始 %d 行 -> 过滤后 %d 行（所需月份 %d 个）",
        len(cleaned), len(filtered), len(required_set),
    )

    # ---- 第二步：构建月度明细 CSV ----
    filtered = filtered.sort_values(["customer", "year", "month"])
    monthly_csv = _df_to_csv(filtered)
    logger.info("月度明细 CSV 字符数: %d", len(monthly_csv))

    # 始终发送完整月度明细数据（不再自动降级为季度聚合）
    # 注：_build_quarterly_csv 函数保留作为备用，如需恢复降级可在此处重新启用
    return monthly_csv, None


def _df_to_csv(data: pd.DataFrame) -> str:
    """将已排序的 DataFrame 转为标准 CSV 文本（含表头，不含索引）。"""
    lines = ["客户代码,月份,保费,单量"]
    for r in data.itertuples(index=False):
        lines.append(
            "%s,%04d-%02d,%.2f,%d" % (r.customer, r.year, r.month, r.premium, r.policies)
        )
    csv_text = "\n".join(lines)

    # 在 CSV 末尾追加汇总行，帮助 LLM 准确引用总数（避免自行累加产生幻觉）
    if len(data) > 0:
        total_premium = data["premium"].sum()
        total_policies = data["policies"].sum()
        csv_text += "\n--- 汇总 ---\nTOTAL,,%.2f,%d" % (total_premium, total_policies)

    return csv_text


def _month_to_quarter(year: int, month: int) -> str:
    """将年月转换为季度标签，如 (2026, 2) -> '26Q1'。"""
    q = (month - 1) // 3 + 1
    return "%dQ%d" % (year % 100, q)


def _build_quarterly_csv(data: pd.DataFrame, extra_months: Optional[set] = None) -> str:
    """将月度明细按 客户×季度 聚合求和，生成降级 CSV。

    季度标签格式：25Q4 / 26Q1 / 26Q2 等。
    特殊处理：2026-07 不属于标准季度，归入 '26Q3' 标签以保持数据完整。

    降级时额外保留 2026-06 和 2026-07 的月度明细数据，确保表3（月度对比）
    能够正常生成。输出格式：先季度聚合数据，再月度明细（注释分隔）。
    """
    # ---- 第一部分：按 客户×季度 聚合求和 ----
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

    # ---- 第二部分：保留指定月份的月度明细（用于月度环比等对比） ----
    # extra_months 由调用方传入，标识哪些月份需要保留月度明细
    # 若未传入则不附加月度明细（向后兼容：调用方应传入最后2个月）
    _extra = extra_months or set()
    monthly_detail_rows: List[str] = []
    for r in data.itertuples(index=False):
        if (r.year, r.month) in _extra:
            monthly_detail_rows.append(
                "%s,%04d-%02d,%.2f,%d" % (r.customer, r.year, r.month, r.premium, r.policies)
            )

    if monthly_detail_rows:
        # 添加注释分隔行，区分季度聚合数据与月度明细数据
        _extra_labels = sorted("%04d-%02d" % (y, m) for y, m in _extra)
        lines.append("# --- 以下为月度明细（%s） ---" % ", ".join(_extra_labels))
        lines.extend(monthly_detail_rows)
        logger.info(
            "降级CSV附加月度明细: %d 行（%s）",
            len(monthly_detail_rows), ", ".join(_extra_labels),
        )

    csv_text = "\n".join(lines)
    logger.info("季度聚合 CSV 字符数: %d（%d 行聚合 + %d 行月度明细）",
                len(csv_text), len(sorted_keys), len(monthly_detail_rows))

    # 在降级 CSV 末尾也追加汇总行，保持与月度明细一致
    if len(data) > 0:
        total_premium = data["premium"].sum()
        total_policies = data["policies"].sum()
        csv_text += "\n--- 汇总 ---\nTOTAL,,%.2f,%d" % (total_premium, total_policies)

    return csv_text






@router.get("/anomaly/default-prompt")
def default_prompt():
    """返回默认提示词，供前端编辑区初始化。优先返回用户保存的版本。"""
    return {"prompt": prompt_store.get("default")}


@router.post("/anomaly/save-prompt")
def save_prompt(req: SavePromptRequest):
    """保存用户编辑的提示词到 JSON 文件（user_prompt.json）。

    请求体: {"prompt": "用户编辑的提示词内容"}
    处理流程：通过 PromptStore 将提示词持久化到 JSON 文件，
    而非写入 prompts.py 源文件，避免部署时 Git 覆盖导致丢失。
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="提示词不能为空")

    try:
        # 使用 PromptStore 保存到 JSON 文件（而非 prompts.py 源文件）
        prompt_store.save("default", req.prompt)
        logger.info("提示词已保存到 user_prompt.json（长度 %d 字符）", len(req.prompt))
        return {"success": True, "message": "提示词已保存"}
    except Exception as exc:
        logger.error("保存提示词失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"保存失败: {str(exc)}")


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
        # 根据前端传入的起止月份动态筛选，未传时回退到 REQUIRED_MONTHS
        months = _resolve_months(req.start_month, req.end_month)
        try:
            csv_text, warning = _build_csv(df, months=months, session_id=req.session_id)
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
                "content": "以下是数据：\n```csv\n%s\n```\n\n请根据规则输出分析结果" % csv_text,
            },
        ]
        payload = {
            "model": cfg["model"],
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
            # DashScope qwen3.7-plus OpenAI 兼容接口：enable_thinking 控制是否开启思考过程
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
                        # 检测 DashScope 返回的 error 事件（HTTP 200 但 body 含 error）
                        if "error" in chunk:
                            err = chunk["error"]
                            err_msg = err.get("message", "模型返回未知错误")
                            logger.error("模型返回错误: %s", err_msg)
                            yield _sse({"type": "error", "message": err_msg})
                            return

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


# ============================================================
# 可配置规则引擎接口
# ============================================================

from io import StringIO
from ..rule_loader import get_rule_config, save_rule_config
from ..configurable_engine import execute_rules


class RulesAnalyzeRequest(BaseModel):
    """POST /anomaly/rules-analyze 请求体。"""
    session_id: str


@router.post("/anomaly/rules-analyze")
async def rules_analyze(req: RulesAnalyzeRequest):
    """执行可配置规则引擎分析，返回结构化结果。"""
    df = store.get(req.session_id)
    if df is None:
        logger.info("rules-analyze 会话不存在或已过期: %s", req.session_id)
        raise HTTPException(404, "会话不存在或已过期，请重新上传")

    # 优先使用用户确认的 mapping，保证与业绩分析数据一致
    columns = [str(c) for c in df.columns if str(c) != "__orig_idx__"]
    mapping = store.get_mapping(req.session_id)
    if mapping is None:
        mapping = parser.auto_map_columns(columns)
        logger.info("rules-analyze 未找到用户确认的 mapping，使用自动识别: %s", mapping)
    else:
        logger.info("rules-analyze 使用用户确认的 mapping: session=%s, mapping=%s", req.session_id, mapping)
    if any(v is None for v in mapping.values()):
        raise HTTPException(400, "无法自动识别数据列（需包含 客户代码/签单时间/保费量/出单量）")

    # 清洗数据
    parsed = parser.extract_records(df, mapping)
    cleaned = parsed["cleaned"]
    if cleaned.empty:
        raise HTTPException(400, "未找到有效的数据记录")

    # 获取规则配置并执行
    config = get_rule_config()
    results = execute_rules(cleaned, config)
    logger.info("规则引擎分析完成: session=%s, 结果表数=%d", req.session_id, len(results))

    return {"tables": results}


@router.get("/anomaly/rules-config")
async def get_rules_config():
    """获取当前规则配置。"""
    return get_rule_config()


@router.put("/anomaly/rules-config")
async def update_rules_config(config: dict):
    """保存规则配置到 JSON 文件。"""
    try:
        saved = save_rule_config(config)
        logger.info("规则配置已更新")
        return {"success": True, "message": "规则配置已保存"}
    except Exception as e:
        logger.error("保存规则配置失败: %s", e)
        raise HTTPException(400, f"保存失败: {str(e)}")



@router.post("/anomaly/rules-config/reset")
async def reset_rules_config():
    """恢复默认规则配置（重新从 rules_config.json 加载）"""
    try:
        from ..rule_loader import load_rule_config
        config = load_rule_config()
        logger.info("规则配置已恢复为默认")
        return {"success": True, "message": "规则配置已恢复为默认"}
    except Exception as e:
        logger.error("恢复默认规则配置失败: %s", e)
        raise HTTPException(400, f"恢复失败: {str(e)}")


@router.get("/anomaly/rules-export")
async def rules_export(
    session_id: str,
    table_id: str = "",
    format: str = "csv"
):
    """导出规则分析结果为 CSV 或 XLSX。"""
    df = store.get(session_id)
    if df is None:
        logger.info("rules-export 会话不存在或已过期: %s", session_id)
        raise HTTPException(404, "会话不存在或已过期")

    # 优先使用用户确认的 mapping，保证与业绩分析数据一致
    columns = [str(c) for c in df.columns if str(c) != "__orig_idx__"]
    mapping = store.get_mapping(session_id)
    if mapping is None:
        mapping = parser.auto_map_columns(columns)
        logger.info("rules-export 未找到用户确认的 mapping，使用自动识别: %s", mapping)
    else:
        logger.info("rules-export 使用用户确认的 mapping: session=%s, mapping=%s", session_id, mapping)
    if any(v is None for v in mapping.values()):
        raise HTTPException(400, "无法自动识别数据列")

    parsed = parser.extract_records(df, mapping)
    cleaned = parsed["cleaned"]
    config = get_rule_config()
    results = execute_rules(cleaned, config)

    # 如果指定了 table_id，只导出该表
    if table_id:
        results = [t for t in results if t["id"] == table_id]
        if not results:
            raise HTTPException(404, f"未找到规则表: {table_id}")

    if format == "csv":
        # CSV 导出（单表或多表合并）
        import csv
        output = StringIO()
        for i, table in enumerate(results):
            if i > 0:
                output.write("\n\n")
            output.write(f"# {table['name']}\n")
            if table['rows']:
                writer = csv.DictWriter(output, fieldnames=table['columns'])
                writer.writeheader()
                writer.writerows(table['rows'])

        output.seek(0)
        logger.info("导出 CSV: session=%s, tables=%d", session_id, len(results))
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=anomaly_rules.csv"}
        )

    elif format == "xlsx":
        # XLSX 导出（每表一个 sheet）
        import openpyxl
        wb = openpyxl.Workbook(write_only=True)
        for table in results:
            ws = wb.create_sheet(title=table["name"][:31])  # sheet名最长31字符
            ws.append(table["columns"])
            for row in table["rows"]:
                ws.append([row.get(c, "") for c in table["columns"]])

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        logger.info("导出 XLSX: session=%s, tables=%d", session_id, len(results))
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=anomaly_rules.xlsx"}
        )

    else:
        raise HTTPException(400, f"不支持的导出格式: {format}")
