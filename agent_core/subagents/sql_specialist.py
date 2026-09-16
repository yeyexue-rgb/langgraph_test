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
    subagent_handle_errors,
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
            handle_errors=subagent_handle_errors,
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
        """按自然语言查询测试管理数据库。

        容错：模型偶发不调用结构化输出工具（最后一条是空 AI 消息），
        此时子 Agent 拿不到 SubagentResult。最多重试两次；重试时在
        输入末尾追加引导提示，避免盲目重掷骰子把"模型抖动"
        直接暴露成 INVALID_SUBAGENT_RESULT。
        """

        import json

        user_messages = [
            {
                "role": "user",
                "content": (
                    "请回答以下测试管理相关问题："
                    f"{query}"
                ),
            }
        ]

        retry_messages = user_messages + [
            {
                "role": "user",
                "content": (
                    "注意：上一次运行结束时没有提交符合 "
                    "SubagentResult 结构的最终结果。请重新完成任务，"
                    "并在结束前调用 SubagentResult 工具提交结构化结果。"
                ),
            }
        ]

        result = ""

        for attempt in range(3):
            state = sql_agent.invoke(
                {
                    "messages": (
                        user_messages
                        if attempt == 0
                        else retry_messages
                    )
                }
            )

            result = serialize_subagent_result(
                state,
                expected_agent="sql_specialist",
                tracer=tracer,
                business_tool_names=business_tool_names,
            )

            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                return result

            if parsed.get("error_code") != "INVALID_SUBAGENT_RESULT":
                return result

        return result

    return call_sql_specialist
