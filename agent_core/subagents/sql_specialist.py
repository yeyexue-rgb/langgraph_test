"""SQL 领域子 Agent 及其 Supervisor 包装工具。

面向测试工程师：查询测试用例库、缺陷统计、测试执行结果。
持有四个 SQL 工具（list_tables / schema / query / query_checker），
挂载 HITL 中间件拦截 sql_db_query 的写操作或危险查询——
对齐官方 SQL Agent 教程第 7 节。

安全约束：
- 工具层：SQLAgentService 校验只读、强制 LIMIT；
- 审批层：HITL 谓词拦截非 SELECT 查询，中断状态由
  Supervisor 的 checkpointer 持久化。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool

from agent_core.hitl import build_hitl_middleware
from agent_core.subagents.contracts import (
    SubagentResult,
    serialize_subagent_result,
)
from agent_core.subagents.tracing import SubagentTracer
from agent_core.prompt_manager import load_prompt


def is_potentially_dangerous_query(request: Any) -> bool:
    """when 谓词：拦截可能危险的 SQL 查询。

    拦截条件：
    - 非 SELECT 开头（写操作即使工具层会拦截，也先审批）；
    - 包含 DROP/DELETE/UPDATE/INSERT/ALTER/CREATE/TRUNCATE 关键字。

    工具层 SQLAgentService 会二次校验只读约束，
    形成审批层 + 工具层双保险。
    """

    tool_call = getattr(request, "tool_call", None)

    if not isinstance(tool_call, dict):
        return False

    args = tool_call.get("args")

    if not isinstance(args, dict):
        return False

    query = str(args.get("query", "")).strip().upper()

    if not query:
        return False

    # 非 SELECT 开头 → 需要审批
    if not query.startswith("SELECT"):
        return True

    # 即使 SELECT 开头，嵌入写操作关键字也要拦截
    dangerous_keywords = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "REPLACE",
        "ATTACH",
        "DETACH",
    )

    for keyword in dangerous_keywords:
        if keyword in query:
            return True

    return False


def create_sql_specialist_tool(
    *,
    model: Any,
    sql_tools: list[Any],
    tracer: SubagentTracer,
    business_tool_names: set[str],
) -> Any:
    """构建 SQL 子 Agent，并包装为 Supervisor 可调用的工具。

    子 Agent 内部挂载 HITL 中间件拦截 sql_db_query 的危险查询，
    对齐官方 SQL Agent 教程第 7 节。
    """

    sql_agent = create_agent(
        model=model,
        tools=sql_tools,
        system_prompt=load_prompt("sql_specialist"),
        middleware=[
            build_hitl_middleware(
                interrupt_on={
                    "sql_db_query": {
                        "allowed_decisions": [
                            "approve",
                            "edit",
                            "reject",
                        ],
                        "when": is_potentially_dangerous_query,
                    },
                },
                description_prefix=(
                    "SQL 子 Agent：以下查询等待人工审批"
                ),
            ),
        ],
        response_format=ToolStrategy(
            schema=SubagentResult,
            handle_errors=(
                "结果必须符合 SubagentResult 结构。"
                "status 只能使用指定枚举值；summary 不能为空；"
                "没有明确错误代码时 error_code 必须为 null；"
                "不得编造查询结果或错误代码。"
            ),
        ),
    )

    @tool(
        "sql_specialist",
        description=(
            "查询测试管理数据库（用例库/缺陷/执行记录）。"
            "支持查询测试用例、缺陷统计、测试执行结果。"
            "传入自然语言查询请求，例如"
            "'哪个模块缺陷率最高'或'本周哪些用例没跑'。"
        ),
    )
    def call_sql_specialist(query: str) -> str:
        """按自然语言查询测试管理数据库。"""

        state = sql_agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "请回答以下测试管理相关问题："
                            f"{query}"
                        ),
                    }
                ]
            }
        )

        return serialize_subagent_result(
            state,
            expected_agent="sql_specialist",
            tracer=tracer,
            business_tool_names=business_tool_names,
        )

    return call_sql_specialist
