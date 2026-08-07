"""pytest 公共 fixtures 与工具。"""
import io
import sys
from pathlib import Path

import pandas as pd
import pytest

# 保证 backend 根目录在 sys.path（python -m pytest 从 backend 目录运行时已包含）
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

COLS = ["签单时间", "客户代码", "保费量", "出单量"]


def make_xlsx_bytes(rows, columns=None):
    """构造内存 xlsx 字节流。"""
    df = pd.DataFrame(rows, columns=columns or COLS)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def make_xlsx_bytes_with_blank_rows(rows, blank_rows=2, columns=None):
    """构造带全空行的 xlsx 字节流（纯空白单元格，后端判为空行剔除）。"""
    from openpyxl import Workbook

    cols = columns or COLS
    wb = Workbook()
    ws = wb.active
    ws.append(cols)
    for r in rows:
        ws.append(r)
    for _ in range(blank_rows):
        ws.append([" "] * len(cols))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_cleaned(rows):
    """构造规则/聚合用的客户×月聚合 DataFrame。rows: (customer, year, month, premium, policies)"""
    return pd.DataFrame(
        rows, columns=["customer", "year", "month", "premium", "policies"]
    )


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
