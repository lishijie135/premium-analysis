"""upload / analyze 路由。"""
import os
from typing import Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import aggregator, config, parser, rules
from ..schemas import AnalyzeRequest
from ..session_store import store

router = APIRouter()


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    name = file.filename or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in (".xlsx", ".xls"):
        raise _error(400, "仅支持 .xlsx / .xls 格式的 Excel 文件")
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise _error(400, "文件大小超过 50MB 限制")
    try:
        df, warnings = parser.read_first_sheet(content)
    except Exception:
        raise _error(400, "无法解析 Excel 文件，请确认为有效的 Excel 格式")

    columns: List[str] = [str(c) for c in df.columns if str(c) != "__orig_idx__"]
    mapping = parser.auto_map_columns(columns)
    need_manual = any(v is None for v in mapping.values())
    preview_rows = parser.build_preview(
        df.drop(columns=["__orig_idx__"], errors="ignore")
    )

    session_id = store.put(df)
    return {
        "session_id": session_id,
        "columns": columns,
        "preview_rows": preview_rows,
        "auto_mapping": mapping,
        "need_manual": need_manual,
        "warnings": warnings,
    }


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    df = store.get(req.session_id)
    if df is None:
        raise _error(404, "会话不存在或已过期，请重新上传文件")

    columns = [str(c) for c in df.columns if str(c) != "__orig_idx__"]
    mapping: Dict[str, Optional[str]] = req.mapping.model_dump()
    for field in ("customer", "date", "premium", "policies"):
        col = mapping.get(field)
        if not col or col not in columns:
            raise _error(400, "列映射无效：%s 对应的列 '%s' 不存在" % (field, col))

    # 保存用户确认的 mapping 到会话存储，供 AI 分析复用（避免 auto_map_columns 选到不同列）
    store.put_mapping(req.session_id, mapping)

    parsed = parser.extract_records(df, mapping)
    cleaned: pd.DataFrame = parsed["cleaned"]

    performance = aggregator.aggregate_performance(cleaned)
    anomalies, growth = rules.analyze_rules(cleaned)

    if len(cleaned) > 0:
        idx = cleaned["year"] * 12 + (cleaned["month"] - 1)
        lo, hi = int(idx.min()), int(idx.max())
        month_range = [_idx_label(lo), _idx_label(hi)]
    else:
        month_range = None

    summary = {
        "total_rows": parsed["total_rows"],
        "valid_rows": parsed["valid_rows"],
        "invalid_rows": parsed["invalid_rows"],
        "duplicate_rows": parsed["duplicate_rows"],
        "invalid_samples": parsed["invalid_samples"],
        "customer_count": int(cleaned["customer"].nunique()) if len(cleaned) else 0,
        "month_range": month_range,
    }

    return {
        "summary": summary,
        "performance": performance,
        "anomalies": anomalies,
        "growth": growth,
    }


def _idx_label(idx: int) -> str:
    year, month = divmod(idx, 12)
    return "%04d-%02d" % (year, month + 1)
