"""冒烟测试：TestClient 走 upload → analyze 全链路（内存小 xlsx）。"""
import pytest

from tests.conftest import COLS, make_xlsx_bytes


def _upload(client, xlsx_bytes, filename="data.xlsx"):
    return client.post(
        "/api/upload",
        files={"file": (filename, xlsx_bytes, "application/octet-stream")},
    )


def _rows():
    rows = [
        ["2025-01", "C001", 10000.0, 2],
        ["2025-02", "C001", 12000.0, 3],
        ["2026-01", "C001", 4000.0, 1],   # 同比腰斩 → D/E
        ["2026-02", "C001", 2000.0, 1],
        ["2026-01", "C002", 5000.0, 2],   # 今年新增 → H
        ["2026-02", "C002", 6000.0, 3],
        ["2026-07", "C003", 800.0, 2],    # 锚定全局最大月 2026-07
    ]
    return rows


class TestSmoke:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_upload_bad_ext(self, client):
        resp = _upload(client, b"hello", filename="data.txt")
        assert resp.status_code == 400

    def test_upload_and_analyze_full_flow(self, client):
        resp = _upload(client, make_xlsx_bytes(_rows()))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_id"]
        assert body["columns"] == COLS
        assert len(body["preview_rows"]) <= 10
        assert body["auto_mapping"] == {
            "customer": "客户代码",
            "date": "签单时间",
            "premium": "保费量",
            "policies": "出单量",
        }
        assert body["need_manual"] is False
        assert isinstance(body["warnings"], list)

        resp2 = client.post(
            "/api/analyze",
            json={"session_id": body["session_id"], "mapping": body["auto_mapping"]},
        )
        assert resp2.status_code == 200, resp2.text
        result = resp2.json()
        assert set(result.keys()) == {"summary", "performance", "anomalies", "growth"}

        s = result["summary"]
        assert s["total_rows"] == 7
        assert s["valid_rows"] == 7
        assert s["invalid_rows"] == 0
        assert s["duplicate_rows"] == 0
        assert s["customer_count"] == 3
        assert s["month_range"] == ["2025-01", "2026-07"]

        perf = result["performance"]
        assert any(x["period"] == "2026-01" for x in perf["monthly"])
        assert any(x["period"] == "2025-Q1" for x in perf["quarterly"])
        assert any(x["period"] == "2025" for x in perf["yearly"])
        assert perf["year_compare"]["years"] == [2025, 2026]

        ano = result["anomalies"]
        assert set(ano.keys()) == {
            "A_premium_monthly_drop",
            "B_volume_monthly_drop",
            "C_inactive",
            "D_premium_yoy_drop",
            "E_volume_yoy_drop",
        }
        d_customers = [x["customer"] for x in ano["D_premium_yoy_drop"]]
        assert "C001" in d_customers

        growth = result["growth"]
        assert set(growth.keys()) == {
            "F_premium_yoy_growth",
            "G_volume_yoy_growth",
            "H_new_customers",
        }
        h_customers = [x["customer"] for x in growth["H_new_customers"]]
        assert "C002" in h_customers

    def test_analyze_unknown_session(self, client):
        resp = client.post(
            "/api/analyze",
            json={
                "session_id": "nonexistent",
                "mapping": {
                    "customer": "客户代码",
                    "date": "签单时间",
                    "premium": "保费量",
                    "policies": "出单量",
                },
            },
        )
        assert resp.status_code == 404

    def test_analyze_bad_mapping(self, client):
        resp = _upload(client, make_xlsx_bytes(_rows()))
        session_id = resp.json()["session_id"]
        resp2 = client.post(
            "/api/analyze",
            json={
                "session_id": session_id,
                "mapping": {
                    "customer": "不存在的列",
                    "date": "签单时间",
                    "premium": "保费量",
                    "policies": "出单量",
                },
            },
        )
        assert resp2.status_code == 400

    def test_header_only_no_500(self, client):
        resp = _upload(client, make_xlsx_bytes([]))
        assert resp.status_code == 200
        body = resp.json()
        resp2 = client.post(
            "/api/analyze",
            json={"session_id": body["session_id"], "mapping": body["auto_mapping"]},
        )
        assert resp2.status_code == 200
        assert resp2.json()["summary"]["total_rows"] == 0
