"""rules 单元测试：A~H 每规则边界参数化。"""
import pytest

from app import rules
from tests.conftest import make_cleaned


def _customers(anomaly_or_growth_list):
    return [x["customer"] for x in anomaly_or_growth_list]


def _analyze(df):
    return rules.analyze_rules(df)


class TestABThreshold:
    """恰好 30.0% 不触发 / 30.1% 触发（连续 ≥2 段）。"""

    @pytest.mark.parametrize(
        "v2,v3,hit",
        [
            (700.0, 490.0, False),   # 恰 30.0%：不触发
            (699.0, 488.0, True),    # 30.1%+30.18%：触发
        ],
    )
    def test_a_drop_threshold(self, v2, v3, hit):
        df = make_cleaned(
            [
                ("T1", 2026, 1, 1000.0, 1),
                ("T1", 2026, 2, v2, 1),
                ("T1", 2026, 3, v3, 1),
                ("X", 2026, 7, 10.0, 1),  # 锚定全局最大月
            ]
        )
        anomalies, _ = _analyze(df)
        assert ("T1" in _customers(anomalies["A_premium_monthly_drop"])) is hit

    def test_a_run_detail(self):
        df = make_cleaned(
            [
                ("T1", 2026, 1, 1000.0, 1),
                ("T1", 2026, 2, 600.0, 1),
                ("T1", 2026, 3, 300.0, 1),
                ("X", 2026, 7, 10.0, 1),
            ]
        )
        anomalies, _ = _analyze(df)
        item = [x for x in anomalies["A_premium_monthly_drop"] if x["customer"] == "T1"][0]
        assert item["months"] == ["2026-01", "2026-02", "2026-03"]
        assert item["premiums"] == [1000.0, 600.0, 300.0]
        assert item["monthly_change_pct"][0] is None
        assert item["monthly_change_pct"][1] == -40.0
        assert item["monthly_change_pct"][2] == -50.0

    def test_b_volume_drop(self):
        df = make_cleaned(
            [
                ("T1", 2026, 1, 5000.0, 8),
                ("T1", 2026, 2, 5000.0, 4),
                ("T1", 2026, 3, 5000.0, 1),
                ("X", 2026, 7, 10.0, 1),
            ]
        )
        anomalies, _ = _analyze(df)
        assert "T1" in _customers(anomalies["B_volume_monthly_drop"])
        assert "T1" not in _customers(anomalies["A_premium_monthly_drop"])  # 保费持平


class TestMinPolicies:
    """恰好 2 单参与 / 1 单忽略。"""

    def test_two_policies_join(self):
        df = make_cleaned(
            [
                ("T1", 2026, 1, 1000.0, 1),
                ("T1", 2026, 2, 600.0, 1),
                ("T1", 2026, 3, 300.0, 0),
                ("X", 2026, 7, 10.0, 1),
            ]
        )
        anomalies, _ = _analyze(df)
        assert "T1" in _customers(anomalies["A_premium_monthly_drop"])

    def test_one_policy_ignored(self):
        df = make_cleaned(
            [
                ("T1", 2026, 1, 1000.0, 1),
                ("T1", 2026, 2, 600.0, 0),
                ("T1", 2026, 3, 300.0, 0),
                ("X", 2026, 7, 10.0, 1),
            ]
        )
        anomalies, growth = _analyze(df)
        for key in anomalies:
            assert "T1" not in _customers(anomalies[key]), key
        for key in ("F_premium_yoy_growth", "G_volume_yoy_growth"):
            assert "T1" not in _customers(growth[key]), key


class TestContinuity:
    def test_prev_zero_skip(self):
        """上月值=0 的段跳过不判定：1000→0 为一段，0→600 跳过，不足连续 2 段。"""
        df = make_cleaned(
            [
                ("T1", 2026, 1, 1000.0, 1),
                ("T1", 2026, 2, 0.0, 1),
                ("T1", 2026, 3, 600.0, 1),
                ("X", 2026, 7, 10.0, 1),
            ]
        )
        anomalies, _ = _analyze(df)
        assert "T1" not in _customers(anomalies["A_premium_monthly_drop"])

    def test_gap_breaks_run(self):
        """缺月补0中断连续性：2026-02 缺失 → 1000→0→600，仅 1 段下降。"""
        df = make_cleaned(
            [
                ("T1", 2026, 1, 1000.0, 1),
                ("T1", 2026, 3, 600.0, 1),
                ("X", 2026, 7, 10.0, 1),
            ]
        )
        anomalies, _ = _analyze(df)
        assert "T1" not in _customers(anomalies["A_premium_monthly_drop"])


class TestInactive:
    def test_idle_cases(self):
        df = make_cleaned(
            [
                ("MAX", 2026, 7, 10.0, 1),   # 全局最大月 2026-07
                ("T0", 2026, 7, 10.0, 2),    # idle=0 → 不命中
                ("T1", 2026, 6, 10.0, 2),    # idle=1 → 不命中
                ("T2", 2026, 5, 10.0, 2),    # idle=2 → 命中
                ("T3", 2026, 4, 10.0, 2),    # idle=3 → 命中
            ]
        )
        anomalies, _ = _analyze(df)
        got = {x["customer"]: x["months_idle"] for x in anomalies["C_inactive"]}
        assert "T0" not in got
        assert "T1" not in got
        assert got["T2"] == 2
        assert got["T3"] == 3
        t3 = [x for x in anomalies["C_inactive"] if x["customer"] == "T3"][0]
        assert t3["last_month"] == "2026-04"


class TestYoYRules:
    def _base(self, extra):
        rows = [
            ("ANC", 2026, 7, 10.0, 1),  # 锚定 Y=2026、M=7
        ]
        return make_cleaned(rows + extra)

    @pytest.mark.parametrize(
        "curr,hit_d,hit_f",
        [
            (700.0, False, False),   # 恰 -30.0%：不触发
            (699.0, True, False),    # -30.1%：D 触发
            (1300.0, False, False),  # +30.0%：不触发
            (1301.0, False, True),   # +30.1%：F 触发
        ],
    )
    def test_d_f_threshold(self, curr, hit_d, hit_f):
        df = self._base(
            [
                ("T1", 2025, 1, 1000.0, 1),
                ("T1", 2026, 1, curr, 1),
            ]
        )
        anomalies, growth = _analyze(df)
        assert ("T1" in _customers(anomalies["D_premium_yoy_drop"])) is hit_d
        assert ("T1" in _customers(growth["F_premium_yoy_growth"])) is hit_f

    def test_d_item_fields(self):
        df = self._base(
            [
                ("T1", 2025, 1, 1000.0, 4),
                ("T1", 2026, 1, 400.0, 1),
            ]
        )
        anomalies, _ = _analyze(df)
        item = anomalies["D_premium_yoy_drop"][0]
        assert item["prev_year"] == 2025
        assert item["curr_year"] == 2026
        assert item["prev_premium"] == 1000.0
        assert item["curr_premium"] == 400.0
        assert item["change_pct"] == -60.0
        assert item["prev_policies"] == 4
        assert item["curr_policies"] == 1

    def test_e_g_volume(self):
        df = self._base(
            [
                ("TD", 2025, 1, 100.0, 10),
                ("TD", 2026, 1, 100.0, 4),   # 单量 -60% → E
                ("TG", 2025, 1, 100.0, 4),
                ("TG", 2026, 1, 100.0, 10),  # 单量 +150% → G
            ]
        )
        anomalies, growth = _analyze(df)
        assert "TD" in _customers(anomalies["E_volume_yoy_drop"])
        assert "TG" in _customers(growth["G_volume_yoy_growth"])

    def test_y1_only_after_m_skip(self):
        """Y-1 年 1~M 月无数据（仅 M 之后的数据）→ 不参与 D/E。"""
        df = self._base(
            [
                ("T1", 2025, 8, 5000.0, 5),  # M=7，8 月不参与对比窗口
                ("T1", 2026, 1, 10.0, 1),
            ]
        )
        anomalies, growth = _analyze(df)
        assert "T1" not in _customers(anomalies["D_premium_yoy_drop"])
        assert "T1" not in _customers(anomalies["E_volume_yoy_drop"])
        # 2025 年有记录 → 也不归 H
        assert "T1" not in _customers(growth["H_new_customers"])

    def test_no_prev_year_goes_to_h_not_d(self):
        """跨年缺失：Y-1 年完全无数据的客户归 H 不归 D/E。"""
        df = self._base(
            [
                ("T1", 2024, 1, 9999.0, 9),
                ("T1", 2026, 1, 10.0, 1),
            ]
        )
        anomalies, growth = _analyze(df)
        assert "T1" not in _customers(anomalies["D_premium_yoy_drop"])
        assert "T1" in _customers(growth["H_new_customers"])


class TestNewCustomers:
    def _df(self, extra):
        return make_cleaned([("ANC", 2026, 7, 10.0, 1)] + extra)

    def test_monthly_growth_true(self):
        df = self._df(
            [
                ("H1", 2026, 1, 1000.0, 1),
                ("H1", 2026, 3, 2000.0, 1),
                ("H1", 2026, 5, 3000.0, 1),
            ]
        )
        _, growth = _analyze(df)
        h = [x for x in growth["H_new_customers"] if x["customer"] == "H1"][0]
        assert h["monthly_growth"] is True
        assert h["year"] == 2026
        assert h["premium"] == 6000.0
        assert h["policies"] == 3
        # monthly 只含有数据月份（可缺月，不补0）
        assert [m["month"] for m in h["monthly"]] == ["2026-01", "2026-03", "2026-05"]

    def test_monthly_growth_false(self):
        df = self._df(
            [
                ("H2", 2026, 1, 2000.0, 1),
                ("H2", 2026, 2, 1000.0, 1),
            ]
        )
        _, growth = _analyze(df)
        h = [x for x in growth["H_new_customers"] if x["customer"] == "H2"][0]
        assert h["monthly_growth"] is False

    def test_monthly_growth_null_single_month(self):
        df = self._df([("H3", 2026, 5, 1000.0, 1)])
        _, growth = _analyze(df)
        h = [x for x in growth["H_new_customers"] if x["customer"] == "H3"][0]
        assert h["monthly_growth"] is None

    def test_h_no_min_policies_filter(self):
        """H 不做总单量过滤：仅 1 单的新客户也入 H。"""
        df = self._df([("H4", 2026, 5, 1000.0, 1)])
        _, growth = _analyze(df)
        assert "H4" in _customers(growth["H_new_customers"])
