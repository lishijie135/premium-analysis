"""Pydantic 数据模型。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class ColumnMapping(BaseModel):
    customer: Optional[str] = None
    date: Optional[str] = None
    premium: Optional[str] = None
    policies: Optional[str] = None


class AnalyzeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    mapping: ColumnMapping


# ---- 可配置规则引擎模型 ----

class PeriodSpec(BaseModel):
    """期间规格：年份 + 月份列表。"""
    year: int
    months: List[int]


class Thresholds(BaseModel):
    """阈值配置：保费/单量下降百分比阈值。"""
    premium_drop_pct: float = -30.0
    policies_drop_pct: float = -30.0


class SortBy(BaseModel):
    """排序配置。"""
    field: str
    order: str = "asc"  # "asc" or "desc"


class TableRule(BaseModel):
    """单张表规则定义。"""
    id: str
    name: str
    enabled: bool = True
    type: str = "period_compare"
    base_period: PeriodSpec
    curr_period: PeriodSpec
    thresholds: Thresholds = Thresholds()
    output_columns: List[str] = []
    sort_by: SortBy = SortBy(field="premium_change_pct", order="asc")


class GlobalConfig(BaseModel):
    """全局配置参数。"""
    min_policies: int = 2
    drop_rate: float = 0.30
    min_consecutive: int = 2
    idle_months: int = 2


class RuleConfig(BaseModel):
    """顶层规则配置模型。"""
    version: str = "1.0"
    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    tables: List[TableRule] = []

    class Config:
        populate_by_name = True
