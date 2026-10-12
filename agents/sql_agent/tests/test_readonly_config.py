from __future__ import annotations

from agents.sql_agent.tools.execute_sql import _db_config_from_env
from db_env import readonly_pymysql_config, writer_pymysql_config


def test_sql_agent_connection_requires_dedicated_readonly_credentials(monkeypatch):
    monkeypatch.setenv("AGENTIC_BI_DB_HOST", "db.example")
    monkeypatch.setenv("AGENTIC_BI_DB_PORT", "3306")
    monkeypatch.setenv("AGENTIC_BI_DB_NAME", "agentic_bi")
    monkeypatch.setenv("AGENTIC_BI_DB_READONLY_USER", "agentic_bi_ro")
    monkeypatch.setenv("AGENTIC_BI_DB_READONLY_PASSWORD", "ro-secret")

    config = _db_config_from_env()

    assert config["user"] == "agentic_bi_ro"
    assert config["password"] == "ro-secret"


def test_role_wrappers_make_readonly_and_writer_selection_explicit(monkeypatch):
    monkeypatch.setenv("AGENTIC_BI_DB_HOST", "db.example")
    monkeypatch.setenv("AGENTIC_BI_DB_PORT", "3306")
    monkeypatch.setenv("AGENTIC_BI_DB_NAME", "agentic_bi")
    monkeypatch.setenv("AGENTIC_BI_DB_USER", "agentic_bi_writer")
    monkeypatch.setenv("AGENTIC_BI_DB_PASSWORD", "writer-secret")
    monkeypatch.setenv("AGENTIC_BI_DB_READONLY_USER", "agentic_bi_ro")
    monkeypatch.setenv("AGENTIC_BI_DB_READONLY_PASSWORD", "ro-secret")

    assert readonly_pymysql_config()["user"] == "agentic_bi_ro"
    assert writer_pymysql_config()["user"] == "agentic_bi_writer"


def test_sql_agent_connection_does_not_fallback_to_writer_credentials(monkeypatch):
    monkeypatch.setenv("AGENTIC_BI_DB_HOST", "db.example")
    monkeypatch.setenv("AGENTIC_BI_DB_PORT", "3306")
    monkeypatch.setenv("AGENTIC_BI_DB_NAME", "agentic_bi")
    monkeypatch.setenv("AGENTIC_BI_DB_USER", "agentic_bi_writer")
    monkeypatch.setenv("AGENTIC_BI_DB_PASSWORD", "writer-secret")
    monkeypatch.delenv("AGENTIC_BI_DB_READONLY_USER", raising=False)
    monkeypatch.delenv("AGENTIC_BI_DB_READONLY_PASSWORD", raising=False)

    try:
        _db_config_from_env()
    except ValueError as exc:
        assert "AGENTIC_BI_DB_READONLY_USER" in str(exc)
    else:
        raise AssertionError("SQL Agent 不应回退到写账号")
