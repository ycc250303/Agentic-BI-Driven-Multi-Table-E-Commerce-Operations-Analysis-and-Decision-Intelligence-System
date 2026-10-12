from __future__ import annotations

from agents.sql_agent.tools.execute_sql import (
    _csv_stem,
    _try_write_error_csv,
    _write_query_result_csv,
)


def test_csv_stem_multi_and_single():
    assert _csv_stem("2026-09-11 17-00-00", 2, 4) == "2026-09-11 17-00-00_sql3"
    assert _csv_stem("2026-09-11 17-00-00", 0, 1) == "2026-09-11 17-00-00"


def test_write_csv_no_bom_lf_left_to_right(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_BI_SQL_CSV_DIR", str(tmp_path))
    path = _write_query_result_csv(
        ["customer_state", "total_gmv"],
        [{"customer_state": "SP", "total_gmv": 1.25}],
        file_stem="demo",
    )
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert raw.decode("utf-8") == "customer_state,total_gmv\nSP,1.25\n"
    assert raw.decode("utf-8").splitlines()[0].startswith("customer_state")


def test_write_single_column_left_to_right(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_BI_SQL_CSV_DIR", str(tmp_path))
    path = _write_query_result_csv(
        ["total_gmv"],
        [{"total_gmv": 7090569.24}],
        file_stem="scalar",
    )
    text = path.read_text(encoding="utf-8")
    assert text == "metric,value\ntotal_gmv,7090569.24\n"
    assert "," in text.splitlines()[1]


def test_error_csv_occupies_sql_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_BI_SQL_CSV_DIR", str(tmp_path))
    written = _try_write_error_csv(
        "2026-09-11 17-00-00_sql3", "db_execute", "执行失败：demo"
    )
    path = tmp_path / "2026-09-11 17-00-00_sql3.csv"
    assert written == str(path.resolve())
    text = path.read_text(encoding="utf-8")
    assert text.startswith("error_stage,error_message\n")
    assert "db_execute" in text
