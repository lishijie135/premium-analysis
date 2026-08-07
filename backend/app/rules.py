"""规则引擎：A~H 八类异常/增长清单。

口径（常量见 config.py）：
- 前置过滤：客户总单量 < MIN_POLICIES 不参与 A~G（恰 2 单参与）；H 不过滤。
- 阈值判定全部"严格大于"，浮点容差 EPS。
- 目标年 Y = 数据最新年度；D~G 对比 Y 年 1~M 月与 Y-1 年 1~M 月累计（M=Y年有数据的最大月）。
"""
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from . import config


def _r2(x: float) -> float:
    return round(float(x), 2)


def _r1(x: float) -> float:
    return round(float(x), 1)


def _mlabel(idx: int) -> str:
    year, month = divmod(idx, 12)
    return "%04d-%02d" % (year, month + 1)


def _build_customer_series(
    cleaned: pd.DataFrame,
) -> Dict[str, Dict[int, Tuple[float, int]]]:
    """customer -> {month_idx: (premium, policies)}"""
    series: Dict[str, Dict[int, Tuple[float, int]]] = {}
    for row in cleaned.itertuples(index=False):
        idx = int(row.year) * 12 + (int(row.month) - 1)
        series.setdefault(row.customer, {})[idx] = (
            float(row.premium),
            int(row.policies),
        )
    return series


def _longest_drop_run(values: List[float]) -> Optional[Tuple[int, int]]:
    """在补0后的连续月序列上找最长下降段。

    返回 (start, end)（含端点的序列下标），段内相邻环比下降次数 = end-start；
    需 >= MIN_CONSECUTIVE 才命中。上月值=0 的段跳过不判定（中断连续性）。
    """
    best: Optional[Tuple[int, int]] = None
    start: Optional[int] = None
    for i in range(1, len(values)):
        prev_v, cur_v = values[i - 1], values[i]
        is_drop = prev_v > 0 and (prev_v - cur_v) / prev_v > config.DROP_RATE + config.EPS
        if is_drop:
            if start is None:
                start = i - 1
            end = i
            pairs = end - start
            if pairs >= config.MIN_CONSECUTIVE:
                if best is None or (end - start) > (best[1] - best[0]):
                    best = (start, end)
        else:
            start = None
    return best


def _run_detail(
    idx_range: Tuple[int, int], values: List[float], base_idx: int, as_int: bool
) -> Dict[str, Any]:
    start, end = idx_range
    months = [_mlabel(base_idx + i) for i in range(start, end + 1)]
    vals = values[start : end + 1]
    if as_int:
        seq: List[Any] = [int(round(v)) for v in vals]
    else:
        seq = [_r2(v) for v in vals]
    pcts: List[Optional[float]] = [None]
    for i in range(1, len(vals)):
        prev_v = vals[i - 1]
        pcts.append(_r1((vals[i] - prev_v) / prev_v * 100) if prev_v > 0 else None)
    return {"months": months, "values": seq, "pcts": pcts}


def analyze_rules(cleaned: pd.DataFrame) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """返回 (anomalies, growth)。cleaned 为 parser 输出的客户×月聚合结果。"""
    anomalies: Dict[str, List[Any]] = {
        "A_premium_monthly_drop": [],
        "B_volume_monthly_drop": [],
        "C_inactive": [],
        "D_premium_yoy_drop": [],
        "E_volume_yoy_drop": [],
    }
    growth: Dict[str, List[Any]] = {
        "F_premium_yoy_growth": [],
        "G_volume_yoy_growth": [],
        "H_new_customers": [],
    }
    if cleaned is None or len(cleaned) == 0:
        return anomalies, growth

    series = _build_customer_series(cleaned)
    total_policies = {
        c: sum(p for _, p in months.values()) for c, months in series.items()
    }
    global_max_idx = max(max(m.keys()) for m in series.values())
    target_year = global_max_idx // 12
    prev_year = target_year - 1

    # Y 年有数据的最大月 M（1~12）
    y_months = [
        int(row.month) for row in cleaned.itertuples(index=False) if int(row.year) == target_year
    ]
    max_m = max(y_months)

    for customer in sorted(series.keys()):
        months_map = series[customer]
        eligible = total_policies[customer] >= config.MIN_POLICIES  # A~G 前置过滤
        idxs = sorted(months_map.keys())
        first_idx, last_idx = idxs[0], idxs[-1]

        # ---- A / B：首末出单月之间缺月记0，找最长连续下降段 ----
        if eligible:
            span = list(range(first_idx, last_idx + 1))
            premiums = [months_map.get(i, (0.0, 0))[0] for i in span]
            counts = [float(months_map.get(i, (0.0, 0))[1]) for i in span]

            run = _longest_drop_run(premiums)
            if run is not None:
                d = _run_detail(run, premiums, first_idx, as_int=False)
                anomalies["A_premium_monthly_drop"].append(
                    {
                        "customer": customer,
                        "months": d["months"],
                        "premiums": d["values"],
                        "monthly_change_pct": d["pcts"],
                    }
                )
            run = _longest_drop_run(counts)
            if run is not None:
                d = _run_detail(run, counts, first_idx, as_int=True)
                anomalies["B_volume_monthly_drop"].append(
                    {
                        "customer": customer,
                        "months": d["months"],
                        "counts": d["values"],
                        "monthly_change_pct": d["pcts"],
                    }
                )

            # ---- C：与全局最大月间隔 >= IDLE_MONTHS ----
            months_idle = global_max_idx - last_idx
            if months_idle >= config.IDLE_MONTHS:
                anomalies["C_inactive"].append(
                    {
                        "customer": customer,
                        "last_month": _mlabel(last_idx),
                        "months_idle": months_idle,
                    }
                )

            # ---- D/E/F/G：Y 年 1~M 月 vs Y-1 年 1~M 月累计 ----
            prev_rows = [
                months_map[i]
                for i in idxs
                if i // 12 == prev_year and (i % 12) + 1 <= max_m
            ]
            if prev_rows:  # Y-1 年 1~M 月有数据才参与
                prev_premium = sum(p for p, _ in prev_rows)
                prev_policies = sum(n for _, n in prev_rows)
                curr_rows = [months_map[i] for i in idxs if i // 12 == target_year]
                curr_premium = sum(p for p, _ in curr_rows)
                curr_policies = sum(n for _, n in curr_rows)

                if prev_premium > 0:
                    chg = (curr_premium - prev_premium) / prev_premium
                    if chg < -(config.DROP_RATE + config.EPS):
                        anomalies["D_premium_yoy_drop"].append(
                            _yoy_item(customer, prev_year, target_year,
                                      prev_premium, curr_premium, chg,
                                      prev_policies, curr_policies, kind="premium")
                        )
                    elif chg > config.DROP_RATE + config.EPS:
                        growth["F_premium_yoy_growth"].append(
                            _yoy_item(customer, prev_year, target_year,
                                      prev_premium, curr_premium, chg,
                                      prev_policies, curr_policies, kind="premium")
                        )
                if prev_policies > 0:
                    chg_n = (curr_policies - prev_policies) / prev_policies
                    if chg_n < -(config.DROP_RATE + config.EPS):
                        anomalies["E_volume_yoy_drop"].append(
                            _yoy_item(customer, prev_year, target_year,
                                      prev_premium, curr_premium, chg_n,
                                      prev_policies, curr_policies, kind="policies")
                        )
                    elif chg_n > config.DROP_RATE + config.EPS:
                        growth["G_volume_yoy_growth"].append(
                            _yoy_item(customer, prev_year, target_year,
                                      prev_premium, curr_premium, chg_n,
                                      prev_policies, curr_policies, kind="policies")
                        )

        # ---- H：Y-1 年无任何记录且 Y 年有记录 ----
        has_prev_year = any(i // 12 == prev_year for i in idxs)
        curr_idxs = sorted(i for i in idxs if i // 12 == target_year)
        if not has_prev_year and curr_idxs:
            y_premium = sum(months_map[i][0] for i in curr_idxs)
            y_policies = sum(months_map[i][1] for i in curr_idxs)
            monthly = [
                {
                    "month": _mlabel(i),
                    "premium": _r2(months_map[i][0]),
                    "policies": int(months_map[i][1]),
                }
                for i in curr_idxs
            ]
            if len(curr_idxs) < 2:
                monthly_growth: Optional[bool] = None
            else:
                vals = [months_map[i][0] for i in curr_idxs]
                monthly_growth = all(
                    vals[i] >= vals[i - 1] - config.EPS for i in range(1, len(vals))
                )
            growth["H_new_customers"].append(
                {
                    "customer": customer,
                    "year": target_year,
                    "policies": int(y_policies),
                    "premium": _r2(y_premium),
                    "monthly": monthly,
                    "monthly_growth": monthly_growth,
                }
            )

    return anomalies, growth


def _yoy_item(
    customer: str,
    prev_year: int,
    curr_year: int,
    prev_premium: float,
    curr_premium: float,
    change: float,
    prev_policies: int,
    curr_policies: int,
    kind: str,
) -> Dict[str, Any]:
    base = {
        "customer": customer,
        "prev_year": prev_year,
        "curr_year": curr_year,
    }
    if kind == "premium":
        base.update(
            {
                "prev_premium": _r2(prev_premium),
                "curr_premium": _r2(curr_premium),
                "change_pct": _r1(change * 100),
                "prev_policies": int(prev_policies),
                "curr_policies": int(curr_policies),
            }
        )
    else:
        base.update(
            {
                "prev_policies": int(prev_policies),
                "curr_policies": int(curr_policies),
                "change_pct": _r1(change * 100),
                "prev_premium": _r2(prev_premium),
                "curr_premium": _r2(curr_premium),
            }
        )
    return base
