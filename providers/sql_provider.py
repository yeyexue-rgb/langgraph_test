"""测试管理数据库 SQL 工具集与 Provider。

面向测试工程师的真实场景：查询测试用例库、缺陷统计、测试执行结果。
与官方 SQL Agent 教程对齐，但增加安全约束：
- 只读：禁止 DML（INSERT/UPDATE/DELETE）和 DDL（DROP/ALTER/CREATE）；
- LIMIT 强制：所有 SELECT 最多返回 top_k 行，防止全表扫描；
- 单连接：每次工具调用打开独立连接，防止跨请求状态泄漏。

工具列表（与官方一致）：
- sql_db_list_tables：列出可用表
- sql_db_schema：查看表结构和样本数据
- sql_db_query：执行只读查询
- sql_db_query_checker：执行前 LLM 双重检查
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field


DEFAULT_DATABASE_PATH = Path("data/test_management.db")

# SQL 安全约束
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|ATTACH|DETACH)\b",
    re.IGNORECASE,
)

DEFAULT_TOP_K = 10


class SQLQueryInput(BaseModel):
    """sql_db_query 的参数 schema。"""

    query: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "一条完整且正确的只读 SQL 查询。"
            "禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE。"
        ),
    )


class SQLSchemaInput(BaseModel):
    """sql_db_schema 的参数 schema。"""

    table_names: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "逗号分隔的表名列表，例如 'test_cases, defects'。"
            "先调用 sql_db_list_tables 确认表存在。"
        ),
    )


class SQLQueryCheckerInput(BaseModel):
    """sql_db_query_checker 的参数 schema。"""

    query: str = Field(
        min_length=1,
        max_length=2000,
        description="待双重检查的 SQL 查询。",
    )


def _validate_readonly(query: str) -> None:
    """校验查询是否为只读，拒绝 DML/DDL。"""

    if FORBIDDEN_KEYWORDS.search(query):
        raise ValueError(
            "禁止执行写操作（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE 等）。"
            "本工具只支持只读 SELECT 查询。"
        )


def _ensure_limit(query: str, top_k: int = DEFAULT_TOP_K) -> str:
    """为没有 LIMIT 的 SELECT 追加 LIMIT，防止全表扫描。"""

    stripped = query.strip().rstrip(";")

    if re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
        return stripped

    return f"{stripped} LIMIT {top_k};"


class SQLAgentService:
    """只读 SQL 查询服务，封装安全约束。"""

    def __init__(
        self,
        database_path: str | Path = DEFAULT_DATABASE_PATH,
    ) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(
            str(self.database_path),
            timeout=10,
        )

    def list_tables(self) -> str:
        connection = self._connect()

        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            )
            tables = [
                row[0]
                for row in cursor.fetchall()
                if not row[0].startswith("sqlite_")
            ]
            return ", ".join(tables)
        finally:
            connection.close()

    def get_schema(self, table_names: str) -> str:
        connection = self._connect()

        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            )
            valid_tables = {
                row[0]
                for row in cursor.fetchall()
                if not row[0].startswith("sqlite_")
            }

            results: list[str] = []

            for table in table_names.split(","):
                table = table.strip()

                if table not in valid_tables:
                    results.append(
                        f"Error: table {table!r} not found"
                    )
                    continue

                cursor.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name=?;",
                    (table,),
                )
                schema_row = cursor.fetchone()

                if schema_row:
                    results.append(schema_row[0])

                    try:
                        quoted = '"' + table.replace('"', '""') + '"'
                        cursor.execute(
                            f"SELECT * FROM {quoted} LIMIT 3;"
                        )
                        rows = cursor.fetchall()

                        if rows:
                            col_names = [
                                desc[0]
                                for desc in cursor.description
                            ]
                            results.append(
                                f"/*\n3 rows from {table}:\n"
                                + "\t".join(col_names)
                                + "\n"
                                + "\n".join(
                                    "\t".join(str(x) for x in row)
                                    for row in rows
                                )
                                + "\n*/"
                            )
                    except Exception as exc:
                        results.append(
                            f"Error fetching sample rows: {exc}"
                        )

            return "\n\n".join(results)
        finally:
            connection.close()

    def execute_query(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
    ) -> str:
        _validate_readonly(query)

        safe_query = _ensure_limit(query, top_k)

        connection = self._connect()

        try:
            cursor = connection.cursor()
            cursor.execute(safe_query)
            results = cursor.fetchall()
            return str(results)
        except Exception as exc:
            return f"Error: {exc}"
        finally:
            connection.close()


def create_sql_tools(
    service: SQLAgentService,
    model: Any | None = None,
) -> list[Any]:
    """创建四个 SQL 工具，返回 LangChain Tool 列表。

    sql_db_query_checker 需要 model 做双重检查；
    若 model 为 None，则跳过 LLM 检查直接返回原查询。
    """

    @tool
    def sql_db_list_tables() -> str:
        """列出测试管理数据库中所有可用表。
        输入为空字符串，输出为逗号分隔的表名列表。"""

        return service.list_tables()

    @tool(args_schema=SQLSchemaInput)
    def sql_db_schema(table_names: str) -> str:
        """查看指定表的结构和样本数据。
        先调用 sql_db_list_tables 确认表存在。
        输入示例：table1, table2"""

        return service.get_schema(table_names)

    @tool(args_schema=SQLQueryInput)
    def sql_db_query(query: str) -> str:
        """执行只读 SQL 查询并返回结果。
        禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE。
        查询出错时会返回错误信息，请修正后重试。"""

        return service.execute_query(query)

    @tool(args_schema=SQLQueryCheckerInput)
    def sql_db_query_checker(query: str) -> str:
        """在执行查询前双重检查 SQL 是否正确。
        始终在使用 sql_db_query 前调用本工具。
        检查常见错误：NOT IN 与 NULL、UNION vs UNION ALL、
        数据类型不匹配、JOIN 列错误等。"""

        if model is None:
            return query

        trigger_prompt = (
            f"{query}\n"
            "Double check the sqlite query above for common mistakes:\n"
            "- Using NOT IN with NULL values\n"
            "- Using UNION when UNION ALL should be used\n"
            "- Data type mismatch in predicates\n"
            "- Properly quoting identifiers\n"
            "- Using the correct columns for joins\n\n"
            "If there are mistakes, rewrite the query. "
            "If no mistakes, reproduce the original.\n"
            "Output the final SQL query only.\n\n"
            f"SQL Query: "
        )

        response = model.invoke(trigger_prompt)
        return str(response.content).strip()

    return [
        sql_db_list_tables,
        sql_db_schema,
        sql_db_query,
        sql_db_query_checker,
    ]


SQL_TOOL_NAMES = [
    "sql_db_list_tables",
    "sql_db_schema",
    "sql_db_query",
    "sql_db_query_checker",
]


class SQLAgentProvider:
    """测试管理 SQL 工具提供者。"""

    def __init__(
        self,
        database_path: str | Path = DEFAULT_DATABASE_PATH,
        model: Any | None = None,
    ) -> None:
        self.service = SQLAgentService(database_path)
        self.model = model
        self._tools = create_sql_tools(
            self.service,
            model=model,
        )

    @property
    def name(self) -> str:
        return "sql_agent"

    def get_tools(self) -> list[Any]:
        return self._tools

    def health_check(self) -> dict[str, Any]:
        path = self.service.database_path

        if not path.exists():
            return {
                "status": "unhealthy",
                "tool_count": len(self._tools),
                "message": f"数据库不存在：{path}",
            }

        try:
            tables = self.service.list_tables()

            return {
                "status": "healthy",
                "tool_count": len(self._tools),
                "database_path": str(path),
                "tables": tables,
                "mode": "read_only",
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "tool_count": len(self._tools),
                "message": str(exc),
            }
