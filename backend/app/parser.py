"""Excel 解析模块：读取、列识别、日期/金额归一、剔除与去重。"""
import io
import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from . import config

_MONEY_CLEAN_RE = re.compile(r"[¥￥$元,，\s]")
_EXCEL_EPOCH = datetime(1899, 12, 30)

_RE_YMD = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_RE_YM = re.compile(r"^(\d{4})[-/.](\d{1,2})$")
_RE_YM_CN = re.compile(r"^(\d{4})年(\d{1,2})月?$")


def _blank_mask(df: pd.DataFrame) -> pd.Series:
    """整行全为 NaN/空字符串/纯空白 → 视为空行。"""
    mask = df.isna()
    for col in df.columns:
        if df[col].dtype == object:
            mask[col] = mask[col] | df[col].map(
                lambda v: isinstance(v, str) and v.strip() == ""
            )
    return mask.all(axis=1)


def read_first_sheet(file_bytes: bytes) -> Tuple[pd.DataFrame, List[str]]:
    """读取第一个 sheet，剔除全空行，返回 (df, warnings)。"""
    warnings: List[str] = []
    buf = io.BytesIO(file_bytes)
    try:
        df = pd.read_excel(buf, engine="openpyxl")
    except Exception:
        buf.seek(0)
        df = pd.read_excel(buf)
    df.columns = [str(c).strip() for c in df.columns]
    blank = _blank_mask(df) if len(df) else pd.Series(dtype=bool)
    empty_rows = int(blank.sum()) if len(df) else 0
    if len(df):
        df = df[~blank].copy()
    if empty_rows > 0:
        warnings.append("发现%d个空行已剔除" % empty_rows)
    return df.reset_index(drop=False).rename(columns={"index": "__orig_idx__"}), warnings


def auto_map_columns(columns: List[str]) -> Dict[str, Optional[str]]:
    """按关键词识别四列：先精确后包含。识别不出为 None。"""
    cols = [str(c).strip() for c in columns]
    mapping: Dict[str, Optional[str]] = {}
    for field, keywords in config.COLUMN_KEYWORDS.items():
        matched: Optional[str] = None
        for kw in keywords:
            for c in cols:
                if c == kw:
                    matched = c
                    break
            if matched is not None:
                break
        if matched is None:
            for kw in keywords:
                for c in cols:
                    if kw in c:
                        matched = c
                        break
                if matched is not None:
                    break
        mapping[field] = matched
    return mapping


def build_preview(df: pd.DataFrame, max_rows: int = 10) -> List[List[Any]]:
    """构造预览行（原生 Python 类型，最多 max_rows 行）。"""
    rows: List[List[Any]] = []
    for _, r in df.head(max_rows).iterrows():
        row = []
        for v in r.tolist():
            row.append(_to_native(v))
        rows.append(row)
    return rows


def _to_native(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float, str, bool)):
        return v
    try:
        import numpy as np
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            f = float(v)
            return None if math.isnan(f) else f
    except Exception:
        pass
    return str(v)


def parse_period(value: Any) -> Optional[Tuple[int, int]]:
    """签单时间归一为 (year, month)，多格式兜底；失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.year, value.month
    if isinstance(value, datetime):
        return value.year, value.month
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if n < 60:  # 不可能是合法的 Excel 日期序列值
            return None
        try:
            dt = _EXCEL_EPOCH + timedelta(days=n)
        except OverflowError:
            return None
        if 1900 <= dt.year <= 2100:
            return dt.year, dt.month
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    m = _RE_YMD.match(s)
    if m:
        return _check_ym(int(m.group(1)), int(m.group(2)))
    m = _RE_YM.match(s)
    if m:
        return _check_ym(int(m.group(1)), int(m.group(2)))
    m = _RE_YM_CN.match(s)
    if m:
        return _check_ym(int(m.group(1)), int(m.group(2)))
    # 最后兜底：pandas 解析
    try:
        ts = pd.to_datetime(s, errors="raise")
        return ts.year, ts.month
    except Exception:
        return None


def _check_ym(year: int, month: int) -> Optional[Tuple[int, int]]:
    if 1900 <= year <= 2100 and 1 <= month <= 12:
        return year, month
    return None


def clean_money(value: Any) -> Any:
    """去除 ¥ ￥ $ , ， 元 空格 等符号，返回可转数字的值。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    return _MONEY_CLEAN_RE.sub("", s)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    s = str(value).strip()
    return s == "" or s.lower() in ("nan", "nat", "none")


def extract_records(df: pd.DataFrame, mapping: Dict[str, str]) -> Dict[str, Any]:
    """按 mapping 提取并清洗记录。

    返回 dict：
      cleaned   去重聚合后的 DataFrame(customer, year, month, premium, policies)
      total_rows / valid_rows / invalid_rows / duplicate_rows
      invalid_samples 最多 10 条 [{row, reason, raw}]
    """
    col_customer = mapping["customer"]
    col_date = mapping["date"]
    col_premium = mapping["premium"]
    col_policies = mapping["policies"]

    idx_col = "__orig_idx__" if "__orig_idx__" in df.columns else None

    total_rows = len(df)
    customers: List[str] = []
    years: List[int] = []
    months: List[int] = []
    premiums: List[float] = []
    policies: List[int] = []
    invalid_rows = 0
    invalid_samples: List[Dict[str, Any]] = []

    def _add_sample(excel_row: int, reason: str, r: Any) -> None:
        if len(invalid_samples) < config.MAX_INVALID_SAMPLES:
            raw = {}
            for c in df.columns:
                if c == "__orig_idx__":
                    continue
                raw[str(c)] = _to_native(r[c])
            invalid_samples.append({"row": excel_row, "reason": reason, "raw": raw})

    for pos in range(total_rows):
        r = df.iloc[pos]
        excel_row = int(r[idx_col]) + 2 if idx_col is not None else pos + 2
        vc, vd, vp, vn = r[col_customer], r[col_date], r[col_premium], r[col_policies]
        if _is_blank(vc) or _is_blank(vd) or _is_blank(vp) or _is_blank(vn):
            invalid_rows += 1
            _add_sample(excel_row, "关键列为空", r)
            continue
        period = parse_period(vd)
        if period is None:
            invalid_rows += 1
            _add_sample(excel_row, "日期无法解析", r)
            continue
        premium = pd.to_numeric(clean_money(vp), errors="coerce")
        if premium is None or (isinstance(premium, float) and math.isnan(premium)):
            invalid_rows += 1
            _add_sample(excel_row, "保费量无法解析", r)
            continue
        pol = pd.to_numeric(clean_money(vn), errors="coerce")
        if pol is None or (isinstance(pol, float) and math.isnan(pol)):
            invalid_rows += 1
            _add_sample(excel_row, "出单量无法解析", r)
            continue
        customers.append(str(vc).strip())
        years.append(period[0])
        months.append(period[1])
        premiums.append(float(premium))
        policies.append(int(round(float(pol))))

    parsed_ok = len(customers)
    if parsed_ok > 0:
        cleaned = pd.DataFrame(
            {
                "customer": customers,
                "year": years,
                "month": months,
                "premium": premiums,
                "policies": policies,
            }
        )
        dup_counts = cleaned.groupby(["customer", "year", "month"]).size()
        duplicate_rows = int((dup_counts - 1).clip(lower=0).sum())
        cleaned = (
            cleaned.groupby(["customer", "year", "month"], as_index=False)
            .agg(premium=("premium", "sum"), policies=("policies", "sum"))
        )
    else:
        duplicate_rows = 0
        cleaned = pd.DataFrame(columns=["customer", "year", "month", "premium", "policies"])

    valid_rows = parsed_ok - duplicate_rows
    return {
        "cleaned": cleaned,
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "duplicate_rows": duplicate_rows,
        "invalid_samples": invalid_samples,
    }
