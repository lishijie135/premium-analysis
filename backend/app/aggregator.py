"""聚合模块：客户×月聚合结果 → 月/季/年业绩序列与年度对比。"""
from typing import Any, Dict, List, Optional

import pandas as pd


def _r2(x: float) -> float:
    return round(float(x), 2)


def _r1(x: float) -> float:
    return round(float(x), 1)


def month_label(year: int, month: int) -> str:
    return "%04d-%02d" % (year, month)


def aggregate_performance(cleaned: pd.DataFrame) -> Dict[str, Any]:
    """cleaned: customer/year/month/premium/policies（已按客户×月聚合）。"""
    if cleaned is None or len(cleaned) == 0:
        return {
            "monthly": [],
            "quarterly": [],
            "yearly": [],
            "year_compare": {
                "years": [],
                "premium_by_year": {},
                "policies_by_year": {},
                "yoy": [],
            },
        }

    df = cleaned.copy()
    df["idx"] = df["year"] * 12 + (df["month"] - 1)
    df["quarter"] = (df["month"] - 1) // 3 + 1

    # 客户历史首次出现月（用于 new_customers）
    first_idx = df.groupby("customer")["idx"].min()

    def _period_stats(grouped: pd.DataFrame, label_fn: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for key, g in grouped:
            idx_set = set(g["idx"].unique())
            new_customers = int(sum(1 for fi in first_idx if fi in idx_set))
            out.append(
                {
                    "period": label_fn(key),
                    "premium": _r2(g["premium"].sum()),
                    "policies": int(g["policies"].sum()),
                    "new_customers": new_customers,
                    "active_customers": int(g["customer"].nunique()),
                }
            )
        out.sort(key=lambda x: x["period"])
        return out

    monthly = _period_stats(df.groupby(["year", "month"]), lambda k: month_label(k[0], k[1]))
    quarterly = _period_stats(df.groupby(["year", "quarter"]), lambda k: "%d-Q%d" % (k[0], k[1]))
    yearly = _period_stats(df.groupby("year"), lambda k: str(k))

    # ---- year_compare ----
    years: List[int] = sorted(int(y) for y in df["year"].unique())
    premium_by_year: Dict[str, List[Optional[float]]] = {}
    policies_by_year: Dict[str, List[Optional[int]]] = {}
    yp = df.groupby(["year", "month"]).agg(
        premium=("premium", "sum"), policies=("policies", "sum")
    )
    for y in years:
        p_arr: List[Optional[float]] = []
        n_arr: List[Optional[int]] = []
        for m in range(1, 13):
            if (y, m) in yp.index:
                p_arr.append(_r2(yp.loc[(y, m), "premium"]))
                n_arr.append(int(yp.loc[(y, m), "policies"]))
            else:
                p_arr.append(None)
                n_arr.append(None)
        premium_by_year[str(y)] = p_arr
        policies_by_year[str(y)] = n_arr

    yoy: List[Dict[str, Any]] = []
    for i in range(1, len(years)):
        curr_y, prev_y = years[i], years[i - 1]
        # 截至该年已有数据的最大月 M，按 1~M 月同期累计对比
        m = int(df.loc[df["year"] == curr_y, "month"].max())
        curr = df[(df["year"] == curr_y) & (df["month"] <= m)]
        prev = df[(df["year"] == prev_y) & (df["month"] <= m)]
        cp, np_ = float(curr["premium"].sum()), float(prev["premium"].sum())
        cn, nn = int(curr["policies"].sum()), int(prev["policies"].sum())
        yoy.append(
            {
                "year": curr_y,
                "premium_change_pct": _r1((cp - np_) / np_ * 100) if np_ > 0 else None,
                "policies_change_pct": _r1((cn - nn) / nn * 100) if nn > 0 else None,
            }
        )

    return {
        "monthly": monthly,
        "quarterly": quarterly,
        "yearly": yearly,
        "year_compare": {
            "years": years,
            "premium_by_year": premium_by_year,
            "policies_by_year": policies_by_year,
            "yoy": yoy,
        },
    }
