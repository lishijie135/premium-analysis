"""aggregator 单元测试：月/季/年统计与新增客户数、年度对比。"""
from app import aggregator
from tests.conftest import make_cleaned


class TestPeriodStats:
    def setup_method(self):
        self.df = make_cleaned(
            [
                ("C1", 2024, 1, 100.0, 2),
                ("C1", 2024, 2, 200.0, 3),
                ("C2", 2024, 2, 50.0, 1),
                ("C1", 2024, 4, 80.0, 1),
            ]
        )
        self.perf = aggregator.aggregate_performance(self.df)

    def test_monthly(self):
        m = {x["period"]: x for x in self.perf["monthly"]}
        assert m["2024-01"]["premium"] == 100.0
        assert m["2024-01"]["policies"] == 2
        assert m["2024-01"]["new_customers"] == 1
        assert m["2024-01"]["active_customers"] == 1
        assert m["2024-02"]["premium"] == 250.0
        assert m["2024-02"]["policies"] == 4
        assert m["2024-02"]["new_customers"] == 1  # C2 首次出现
        assert m["2024-02"]["active_customers"] == 2
        assert m["2024-04"]["new_customers"] == 0

    def test_quarterly(self):
        q = {x["period"]: x for x in self.perf["quarterly"]}
        assert q["2024-Q1"]["premium"] == 350.0
        assert q["2024-Q1"]["policies"] == 6
        assert q["2024-Q1"]["new_customers"] == 2
        assert q["2024-Q2"]["premium"] == 80.0
        assert q["2024-Q2"]["new_customers"] == 0

    def test_yearly(self):
        y = {x["period"]: x for x in self.perf["yearly"]}
        assert y["2024"]["premium"] == 430.0
        assert y["2024"]["policies"] == 7
        assert y["2024"]["new_customers"] == 2
        assert y["2024"]["active_customers"] == 2

    def test_empty(self):
        perf = aggregator.aggregate_performance(make_cleaned([]))
        assert perf["monthly"] == []
        assert perf["year_compare"]["years"] == []
        assert perf["year_compare"]["yoy"] == []


class TestYearCompare:
    def test_by_year_and_yoy(self):
        df = make_cleaned(
            [
                ("C1", 2024, 1, 100.0, 2),
                ("C1", 2024, 2, 300.0, 2),
                ("C1", 2025, 1, 150.0, 3),  # 2025 仅到 1 月 → M=1，同期累计对比
            ]
        )
        yc = aggregator.aggregate_performance(df)["year_compare"]
        assert yc["years"] == [2024, 2025]
        assert len(yc["premium_by_year"]["2024"]) == 12
        assert yc["premium_by_year"]["2024"][0] == 100.0
        assert yc["premium_by_year"]["2024"][1] == 300.0
        assert yc["premium_by_year"]["2024"][2] is None
        assert yc["policies_by_year"]["2025"][0] == 3
        assert len(yc["yoy"]) == 1
        yoy = yc["yoy"][0]
        assert yoy["year"] == 2025
        # 2025 年 1 月 150 vs 2024 年 1 月 100 → +50%；单量 3 vs 2 → +50%
        assert yoy["premium_change_pct"] == 50.0
        assert yoy["policies_change_pct"] == 50.0

    def test_yoy_prev_zero_is_none(self):
        df = make_cleaned(
            [
                ("C1", 2024, 5, 100.0, 1),  # 2024 年 1~3 月无数据
                ("C1", 2025, 3, 100.0, 1),
            ]
        )
        yc = aggregator.aggregate_performance(df)["year_compare"]
        # M=3，2024 年 1~3 月累计为 0 → 同比为 null
        assert yc["yoy"][0]["premium_change_pct"] is None
        assert yc["yoy"][0]["policies_change_pct"] is None
