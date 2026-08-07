"""Pydantic 数据模型。"""
from typing import Optional

from pydantic import BaseModel, Field


class ColumnMapping(BaseModel):
    customer: Optional[str] = None
    date: Optional[str] = None
    premium: Optional[str] = None
    policies: Optional[str] = None


class AnalyzeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    mapping: ColumnMapping
