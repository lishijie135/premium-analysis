"""parser 单元测试：日期多格式、金额清洗、空行、重复行、仅表头等。"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app import parser
from tests.conftest import COLS, make_xlsx_bytes, make_xlsx_bytes_with_blank_rows

MAPPING = {"customer": "客户代码", "date": "签单时间", "premium": "保费量", "policies": "出单量"}

_EXCEL_EPOCH = datetime(1899, 12, 30)


def _serial(year, month):
    return (datetime(year, month, 1) - _EXCEL_EPOCH).days


class TestParsePeriod:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-01", (2026, 1)),
            ("2026/2", (2026, 2)),
            ("2026-03-15", (2026, 3)),
            ("2026/4/5", (2026, 4)),
            ("2026年5月", (2026, 5)),
            ("2026年6", (2026, 6)),
            (datetime(2026, 7, 10), (2026, 7)),
            (pd.Timestamp("2026-08-20"), (2026, 8)),
        ],
    )
    def test_formats(self, value, expected):
        assert parser.parse_period(value) == expected

    def test_excel_serial(self):
        serial = _serial(2026, 5)
        assert parser.parse_period(serial) == (2026, 5)
        assert parser.parse_period(float(serial)) == (2026, 5)

    @pytest.mark.parametrize("value", [None, "", "  ", "abc", "2026-13", "13月", float("nan")])
    def test_invalid(self, value):
        assert parser.parse_period(value) is None


class TestCleanMoney:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("¥1,234.56", 1234.56),
            ("￥ 3,000", 3000.0),
            ("$2,500.5", 2500.5),
            ("1,000元", 1000.0),
            ("￥1，000", 1000.0),
            (123.4, 123.4),
            (8, 8),
        ],
    )
    def test_clean(self, value, expected):
        cleaned = parser.clean_money(value)
        assert float(pd.to_numeric(cleaned)) == expected

    @pytest.mark.parametrize("value", [None, "", float("nan")])
    def test_blank(self, value):
        assert parser.clean_money(value) is None


class TestAutoMapColumns:
    def test_exact(self):
        m = parser.auto_map_columns(COLS)
        assert m == {"customer": "客户代码", "date": "签单时间", "premium": "保费量", "policies": "出单量"}

    def test_contains(self):
        m = parser.auto_map_columns(["客户编码A", "保单日期", "总保费(元)", "月出单数"])
        assert m["customer"] == "客户编码A"
        assert m["date"] == "保单日期"
        assert m["premium"] == "总保费(元)"
        assert m["policies"] == "月出单数"

    def test_unknown(self):
        m = parser.auto_map_columns(["甲", "乙", "丙", "丁"])
        assert set(m.values()) == {None}


class TestExtractRecords:
    def _read(self, xlsx_bytes):
        df, warnings = parser.read_first_sheet(xlsx_bytes)
        return df, warnings

    def test_basic_and_duplicates(self):
        data = [
            ["2026-01", "C001", "¥1,000", 2],
            ["2026-01", "C001", 500, 1],  # 重复行，应合并
            ["2026年2月", "C002", "2,000元", 3],
        ]
        df, warnings = self._read(make_xlsx_bytes(data))
        res = parser.extract_records(df, MAPPING)
        assert res["total_rows"] == 3
        assert res["duplicate_rows"] == 1
        assert res["invalid_rows"] == 0
        assert res["valid_rows"] == 2
        c1 = res["cleaned"][(res["cleaned"].customer == "C001")]
        assert float(c1["premium"].iloc[0]) == 1500.0
        assert int(c1["policies"].iloc[0]) == 3

    def test_blank_rows_removed_with_warning(self):
        data = [["2026-01", "C001", 100, 1], ["2026-02", "C001", 200, 2]]
        df, warnings = self._read(make_xlsx_bytes_with_blank_rows(data, blank_rows=3))
        assert any("3个空行" in w for w in warnings)
        res = parser.extract_records(df, MAPPING)
        assert res["total_rows"] == 2
        assert res["valid_rows"] == 2

    def test_invalid_rows_and_samples(self):
        data = [
            ["2026-01", "C001", 100, 1],
            ["无法解析", "C002", 100, 1],       # 日期坏
            ["2026-02", "C003", "abc", 1],       # 保费坏
            [None, "C004", 100, 1],              # 关键列空
        ]
        df, _ = self._read(make_xlsx_bytes(data))
        res = parser.extract_records(df, MAPPING)
        assert res["invalid_rows"] == 3
        assert res["valid_rows"] == 1
        assert len(res["invalid_samples"]) == 3
        assert res["invalid_samples"][0]["row"] == 3  # Excel 行号（含表头偏移）
        assert res["invalid_samples"][0]["reason"] == "日期无法解析"
        assert "raw" in res["invalid_samples"][0]

    def test_header_only_no_error(self):
        df, _ = self._read(make_xlsx_bytes([]))
        assert len(df) == 0
        res = parser.extract_records(df, MAPPING)
        assert res["total_rows"] == 0
        assert res["valid_rows"] == 0
        assert len(res["cleaned"]) == 0

    def test_excel_serial_date_cell(self):
        from openpyxl import Workbook
        import io

        wb = Workbook()
        ws = wb.active
        ws.append(COLS)
        ws.append([datetime(2026, 5, 1), "C001", 100, 1])
        buf = io.BytesIO()
        wb.save(buf)
        df, _ = self._read(buf.getvalue())
        res = parser.extract_records(df, MAPPING)
        assert res["valid_rows"] == 1
        row = res["cleaned"].iloc[0]
        assert (int(row["year"]), int(row["month"])) == (2026, 5)
