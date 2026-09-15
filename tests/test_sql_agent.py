"""SQL Agent 工具层单元测试：只读约束、LIMIT 强制、安全校验。

不依赖大模型，直接调用 SQLAgentService 和工具。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from providers.sql_provider import (
    SQLAgentProvider,
    SQLAgentService,
    _ensure_limit,
    _validate_readonly,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """创建临时测试管理数据库。"""

    db_path = tmp_path / "test_management.db"

    connection = sqlite3.connect(str(db_path))

    try:
        connection.executescript(
            """
            CREATE TABLE test_cases (
                case_id TEXT PRIMARY KEY,
                module TEXT,
                priority TEXT
            );
            CREATE TABLE defects (
                defect_id TEXT PRIMARY KEY,
                severity TEXT,
                status TEXT
            );
            INSERT INTO test_cases VALUES
                ('TC-001', '登录模块', 'P0'),
                ('TC-002', '购物车', 'P1');
            INSERT INTO defects VALUES
                ('DEF-001', 'major', 'open'),
                ('DEF-002', 'minor', 'closed');
            """
        )
        connection.commit()
    finally:
        connection.close()

    return db_path


@pytest.fixture
def service(database_path: Path) -> SQLAgentService:
    return SQLAgentService(database_path)


def invoke_tool(provider: SQLAgentProvider, tool_name: str, args: dict) -> str:
    """直接调用 provider 的指定工具。"""
    for tool in provider.get_tools():
        if tool.name == tool_name:
            return tool.invoke(args)
    raise ValueError(f"工具不存在：{tool_name}")


class TestReadonlyValidation:

    @pytest.mark.parametrize(
        "forbidden_sql",
        [
            "INSERT INTO test_cases VALUES ('TC-X', 'test', 'P0')",
            "UPDATE test_cases SET priority='P1' WHERE case_id='TC-001'",
            "DELETE FROM test_cases WHERE case_id='TC-001'",
            "DROP TABLE test_cases",
            "ALTER TABLE test_cases ADD COLUMN notes TEXT",
            "CREATE TABLE temp (id INTEGER)",
        ],
    )
    def test_dml_ddl_rejected(self, forbidden_sql: str) -> None:
        with pytest.raises(ValueError, match="禁止执行写操作"):
            _validate_readonly(forbidden_sql)

    def test_select_accepted(self) -> None:
        _validate_readonly("SELECT * FROM test_cases")

    def test_select_with_cte_accepted(self) -> None:
        _validate_readonly(
            "WITH t AS (SELECT * FROM test_cases) SELECT * FROM t"
        )


class TestEnsureLimit:

    def test_adds_limit_when_missing(self) -> None:
        result = _ensure_limit("SELECT * FROM test_cases")
        assert "LIMIT 10" in result

    def test_preserves_existing_limit(self) -> None:
        result = _ensure_limit("SELECT * FROM test_cases LIMIT 5")
        # 不重复追加
        assert result.count("LIMIT") == 1

    def test_strips_trailing_semicolon(self) -> None:
        result = _ensure_limit("SELECT * FROM test_cases;")
        assert not result.rstrip().endswith(";;")


class TestSQLAgentService:

    def test_list_tables(self, service: SQLAgentService) -> None:
        tables = service.list_tables()
        assert "test_cases" in tables
        assert "defects" in tables

    def test_get_schema(self, service: SQLAgentService) -> None:
        schema = service.get_schema("test_cases")
        assert "CREATE TABLE" in schema
        assert "test_cases" in schema
        # 包含样本数据
        assert "TC-001" in schema

    def test_get_schema_invalid_table(self, service: SQLAgentService) -> None:
        schema = service.get_schema("nonexistent_table")
        assert "not found" in schema

    def test_execute_query(self, service: SQLAgentService) -> None:
        result = service.execute_query(
            "SELECT COUNT(*) FROM test_cases"
        )
        assert "2" in result

    def test_query_auto_adds_limit(
        self,
        service: SQLAgentService,
    ) -> None:
        result = service.execute_query(
            "SELECT * FROM test_cases"
        )
        # 只返回 LIMIT 后的行
        assert "TC-001" in result
        assert "TC-002" in result

    def test_query_error_returns_message(
        self,
        service: SQLAgentService,
    ) -> None:
        result = service.execute_query(
            "SELECT * FROM nonexistent_table"
        )
        assert "Error" in result

    def test_dml_blocked_at_service_level(
        self,
        service: SQLAgentService,
    ) -> None:
        result = service.execute_query(
            "DELETE FROM test_cases WHERE case_id='TC-001'"
        )
        assert "禁止执行写操作" in result


class TestSQLAgentProvider:

    def test_provider_health_check_healthy(
        self,
        database_path: Path,
    ) -> None:
        provider = SQLAgentProvider(
            database_path=database_path,
            model=None,
        )
        health = provider.health_check()

        assert health["status"] == "healthy"
        assert health["tool_count"] == 4
        assert health["mode"] == "read_only"

    def test_provider_health_check_missing_db(
        self,
        tmp_path: Path,
    ) -> None:
        provider = SQLAgentProvider(
            database_path=tmp_path / "nonexistent.db",
            model=None,
        )
        health = provider.health_check()

        assert health["status"] == "unhealthy"

    def test_provider_returns_four_tools(
        self,
        database_path: Path,
    ) -> None:
        provider = SQLAgentProvider(
            database_path=database_path,
            model=None,
        )
        tools = provider.get_tools()

        assert len(tools) == 4
        names = {t.name for t in tools}
        assert names == {
            "sql_db_list_tables",
            "sql_db_schema",
            "sql_db_query",
            "sql_db_query_checker",
        }

    def test_list_tables_via_tool(
        self,
        database_path: Path,
    ) -> None:
        provider = SQLAgentProvider(
            database_path=database_path,
            model=None,
        )
        result = invoke_tool(provider, "sql_db_list_tables", {})
        assert "test_cases" in result
        assert "defects" in result

    def test_query_via_tool(
        self,
        database_path: Path,
    ) -> None:
        provider = SQLAgentProvider(
            database_path=database_path,
            model=None,
        )
        result = invoke_tool(
            provider,
            "sql_db_query",
            {"query": "SELECT module FROM test_cases"},
        )
        assert "登录模块" in result

    def test_query_checker_without_model_returns_original(
        self,
        database_path: Path,
    ) -> None:
        provider = SQLAgentProvider(
            database_path=database_path,
            model=None,
        )
        result = invoke_tool(
            provider,
            "sql_db_query_checker",
            {"query": "SELECT * FROM test_cases"},
        )
        assert "SELECT" in result
