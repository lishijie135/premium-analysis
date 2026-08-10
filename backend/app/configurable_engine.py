"""可配置规则执行引擎。

根据 JSON 配置对清洗后的 DataFrame 执行期间对比异常筛选规则。
支持多张规则表、可配置阈值、排序和列名映射。
"""

import logging
import math
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---- 内部英文字段名 -> 中文输出列名映射 ----
COLUMN_MAP: dict[str, str] = {
    "customer": "客户代码",
    "base_premium": "基期保费",
    "base_policies": "基期单量",
    "curr_premium": "当期保费",
    "curr_policies": "当期单量",
    "premium_change_pct": "保费环比%",
    "policies_change_pct": "单量环比%",
    "risk_level": "风险等级",
    "unit_premium": "单位保费",
}


def _aggregate_period(cleaned: pd.DataFrame, year: int, months: list[int]) -> pd.DataFrame:
    """聚合指定期间的客户数据。

    Args:
        cleaned: 清洗后的 DataFrame，列: customer, year, month, premium, policies
        year: 年份
        months: 月份列表

    Returns:
        按客户聚合的 DataFrame，列: customer, premium, policies
    """
    mask = (cleaned["year"] == year) & (cleaned["month"].isin(months))
    period_data = cleaned[mask]
    logger.debug("聚合期间 year=%d months=%s，匹配行数=%d", year, months, len(period_data))
    return period_data.groupby("customer").agg(
        premium=("premium", "sum"),
        policies=("policies", "sum"),
    ).reset_index()


def _compute_change_pct(curr: pd.Series, base: pd.Series) -> pd.Series:
    """计算环比变化百分比，分母 <=0 时设为 NaN。

    Args:
        curr: 当期数值序列
        base: 基期数值序列

    Returns:
        环比变化百分比序列（已四舍五入到 2 位小数）
    """
    result = pd.Series(float("nan"), index=curr.index, dtype=float)
    valid = base.abs() > 0
    result[valid] = ((curr[valid] - base[valid]) / base[valid].abs() * 100).round(2)
    return result


def _risk_level(row: dict, premium_drop: float, policies_drop: float) -> str:
    """根据阈值判断风险等级。

    Args:
        row: 单行数据字典（含 premium_change_pct / policies_change_pct）
        premium_drop: 保费下降阈值
        policies_drop: 单量下降阈值

    Returns:
        风险等级字符串
    """
    p_drop = row["premium_change_pct"] <= premium_drop
    s_drop = row["policies_change_pct"] <= policies_drop
    if p_drop and s_drop:
        return "双降预警"
    if p_drop:
        return "保费下降"
    if s_drop:
        return "单量下降"
    return "正常"


def _execute_single_table(cleaned: pd.DataFrame, table_cfg: dict) -> dict:
    """执行单张规则表的异常筛选。

    Args:
        cleaned: 清洗后的 DataFrame
        table_cfg: 单张表的规则配置字典

    Returns:
        结果字典，包含 id / name / columns / rows / summary
    """
    table_id = table_cfg["id"]
    table_name = table_cfg["name"]
    logger.info("开始执行规则表: %s (%s)", table_id, table_name)

    # ---- 解析配置 ----
    base_year = table_cfg["base_period"]["year"]
    base_months = table_cfg["base_period"]["months"]
    curr_year = table_cfg["curr_period"]["year"]
    curr_months = table_cfg["curr_period"]["months"]
    premium_drop = table_cfg["thresholds"]["premium_drop_pct"]
    policies_drop = table_cfg["thresholds"]["policies_drop_pct"]
    sort_field = table_cfg["sort_by"]["field"]
    sort_order = table_cfg["sort_by"]["order"]
    output_columns = table_cfg.get("output_columns", [])

    # ---- 1. 聚合基期 & 当期 ----
    base_df = _aggregate_period(cleaned, base_year, base_months)
    curr_df = _aggregate_period(cleaned, curr_year, curr_months)
    logger.info(
        "[%s] 基期客户数=%d, 当期客户数=%d",
        table_id, len(base_df), len(curr_df),
    )

    # ---- 2. 合并（inner join，只保留两期都有数据的客户） ----
    merged = base_df.merge(curr_df, on="customer", how="inner", suffixes=("_base", "_curr"))
    merged.rename(columns={
        "premium_base": "base_premium",
        "policies_base": "base_policies",
        "premium_curr": "curr_premium",
        "policies_curr": "curr_policies",
    }, inplace=True)
    logger.debug("[%s] 合并后客户数=%d", table_id, len(merged))

    # ---- 3. 计算环比 ----
    merged["premium_change_pct"] = _compute_change_pct(merged["curr_premium"], merged["base_premium"])
    merged["policies_change_pct"] = _compute_change_pct(merged["curr_policies"], merged["base_policies"])

    # ---- 4. 筛选异常（至少满足一个条件） ----
    anomaly_mask = (
        (merged["premium_change_pct"] <= premium_drop)
        | (merged["policies_change_pct"] <= policies_drop)
    )
    anomalies = merged[anomaly_mask].copy()
    logger.info("[%s] 识别异常客户数=%d", table_id, len(anomalies))

    # ---- 5. 标记风险等级 ----
    anomalies["risk_level"] = anomalies.apply(
        lambda r: _risk_level(r.to_dict(), premium_drop, policies_drop), axis=1
    )

    # ---- 6. 计算单位保费（可选） ----
    anomalies["unit_premium"] = anomalies.apply(
        lambda r: round(r["curr_premium"] / r["curr_policies"], 2) if r["curr_policies"] > 0 else float("nan"),
        axis=1,
    )

    # ---- 7. 排序 ----
    ascending = sort_order == "asc"
    if sort_field in anomalies.columns:
        anomalies.sort_values(by=sort_field, ascending=ascending, inplace=True)

    # ---- 8. 构建输出 ----
    # 中文列名 -> 英文字段名 的反向映射
    cn_to_en = {v: k for k, v in COLUMN_MAP.items()}
    if output_columns:
        out_cols_en = [cn_to_en.get(c, c) for c in output_columns if c in cn_to_en or c in anomalies.columns]
    else:
        out_cols_en = [c for c in anomalies.columns if c in COLUMN_MAP]

    # 只保留实际存在的列
    out_cols_en = [c for c in out_cols_en if c in anomalies.columns]

    rows_list: list[dict] = []
    for _, row in anomalies.iterrows():
        out_row: dict[str, Any] = {}
        for col_en in out_cols_en:
            col_cn = COLUMN_MAP.get(col_en, col_en)
            val = row[col_en]
            # 数值保留 2 位小数
            if isinstance(val, float) and not math.isnan(val):
                val = round(val, 2)
            # 环比列添加 % 后缀
            if col_en in ("premium_change_pct", "policies_change_pct") and not math.isnan(val):
                out_row[col_cn] = f"{val}%"
            elif isinstance(val, float) and math.isnan(val):
                out_row[col_cn] = "N/A"
            else:
                out_row[col_cn] = val
        rows_list.append(out_row)

    # ---- 9. 生成 summary ----
    summary = f"共识别 {len(rows_list)} 家异常客户"
    if rows_list:
        # 找到保费降幅最大的客户
        def _extract_pct(r):
            v = r.get("保费环比%", "N/A")
            if v == "N/A":
                return 0.0
            return float(str(v).replace("%", ""))

        worst = min(rows_list, key=_extract_pct)
        worst_pct = worst.get("保费环比%", "N/A")
        summary += f"，最大降幅客户为 {worst['客户代码']}（保费环比 {worst_pct}）"

    logger.info("[%s] 执行完成: %s", table_id, summary)

    return {
        "id": table_id,
        "name": table_name,
        "columns": [COLUMN_MAP.get(c, c) for c in out_cols_en],
        "rows": rows_list,
        "summary": summary,
    }



def _execute_customer_peak(cleaned: pd.DataFrame, table_cfg: dict) -> dict:
    """客户峰值模板：每个客户的最高单量和最高保费。

    Args:
        cleaned: 清洗后的 DataFrame，含 customer/premium/policies 等列
        table_cfg: 单张表的规则配置字典

    Returns:
        结果字典，包含 id / name / columns / rows / summary
    """
    table_id = table_cfg["id"]
    table_name = table_cfg["name"]
    logger.info("执行客户峰值模板: %s (%s)", table_id, table_name)

    # 按客户聚合，取保费和单量的最大值
    peak = cleaned.groupby("customer").agg(
        max_premium=("premium", "max"),
        max_policies=("policies", "max"),
    ).reset_index()

    # 按配置排序（默认 max_premium 降序）
    sort_field = table_cfg.get("sort_by", {}).get("field", "max_premium")
    sort_order = table_cfg.get("sort_by", {}).get("order", "desc")
    if sort_field in peak.columns:
        peak.sort_values(by=sort_field, ascending=(sort_order == "asc"), inplace=True)

    # 构建输出行
    rows_list: list[dict] = []
    for _, row in peak.iterrows():
        rows_list.append({
            "客户代码": row["customer"],
            "最高保费": round(row["max_premium"], 2),
            "最高单量": int(row["max_policies"]),
        })

    # 生成摘要
    summary = f"共 {len(rows_list)} 位客户"
    if rows_list:
        top = rows_list[0]
        summary += f"，最高保费客户为 {top['客户代码']}（保费 {top['最高保费']}，单量 {top['最高单量']}）"

    logger.info("[%s] 客户峰值模板完成: %s", table_id, summary)

    return {
        "id": table_id,
        "name": table_name,
        "columns": ["客户代码", "最高保费", "最高单量"],
        "rows": rows_list,
        "summary": summary,
    }


def execute_rules(cleaned: pd.DataFrame, config: dict) -> list[dict]:
    """执行可配置规则引擎。

    遍历配置中所有 enabled=true 的规则表，依次执行期间对比异常筛选。

    Args:
        cleaned: 清洗后的 DataFrame，列: customer, year, month, premium, policies
        config: 规则配置字典（从 rule_loader.get_rule_config() 获取）

    Returns:
        列表，每个元素对应一张规则表的结果:
        {
            "id": "q2_vs_q1",
            "name": "2026Q2 vs 2026Q1 季度环比",
            "columns": ["客户代码", "基期保费", "基期单量", ...],
            "rows": [{"客户代码": "C001", "基期保费": 10000, ...}, ...],
            "summary": "共识别 X 家异常客户"
        }
    """
    tables = config.get("tables", [])
    enabled_tables = [t for t in tables if t.get("enabled", False)]
    logger.info("规则引擎启动，共 %d 张表规则，其中 %d 张已启用", len(tables), len(enabled_tables))

    results: list[dict] = []
    for table_cfg in enabled_tables:
        try:
            # 根据表类型分发到不同的执行函数
            table_type = table_cfg.get("type", "period_compare")
            if table_type == "customer_peak":
                result = _execute_customer_peak(cleaned, table_cfg)
            else:
                result = _execute_single_table(cleaned, table_cfg)
            results.append(result)
        except Exception:
            logger.exception("执行规则表 [%s] 时发生异常", table_cfg.get("id", "unknown"))
            # 单表失败不影响其他表执行
            results.append({
                "id": table_cfg.get("id", "unknown"),
                "name": table_cfg.get("name", "未知规则"),
                "columns": [],
                "rows": [],
                "summary": "执行异常，请检查日志",
            })

    logger.info("规则引擎执行完毕，共返回 %d 张表结果", len(results))
    return results
