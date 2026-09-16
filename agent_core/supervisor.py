"""Supervisor 多 Agent 架构：主协调 Agent + 三个领域子 Agent。

架构（对上：外部接口与 single 模式完全一致）：
    Supervisor（持有 3 个包装工具：time_specialist / file_specialist / sql_specialist）
        ├── time_specialist  → 5 个时间工具
        ├── file_specialist  → search_personal_space_files（含越界 HITL）
        └── sql_specialist   → sql_db_query / sql_db_schema / sql_db_query_checker（含危险查询 HITL）

要点：
- 子 Agent 无 checkpointer、无记忆，每次调用从干净上下文开始（官方 Subagents 默认行为）；
- 嵌套轨迹由 SubagentTracer 记录，AgentService 负责合并进最终结果；
- 返回 (supervisor_agent, subagent_tool_names)，调用方（AgentService）据此
  扩充业务工具白名单，避免 Supervisor 层包装工具被轨迹过滤掉。
"""
from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

from agent_core.prompt_manager import load_prompt
from agent_core.structured_output import (
    AgentResponse,
    agent_response_handle_errors,
)
from agent_core.subagents.file_specialist import create_file_specialist_tool
from agent_core.subagents.sql_specialist import create_sql_specialist_tool
from agent_core.subagents.time_specialist import create_time_specialist_tool
from agent_core.subagents.tracing import SubagentTracer


TIME_TOOL_NAMES = {
    "parse_natural_datetime",
    "parse_time_range",
    "get_current_time",
    "date_add",
    "date_diff",
}
FILE_TOOL_NAMES = {"search_personal_space_files"}
SQL_TOOL_NAMES = {
    "sql_db_list_tables",
    "sql_db_schema",
    "sql_db_query_checker",
    "sql_db_query",
}

SUBAGENT_TOOL_NAMES = ("time_specialist", "file_specialist", "sql_specialist")


def build_supervisor_agent(
    *,
    model: Any,
    tool_registry: Any,
    checkpointer: Any = None,
    tracer: SubagentTracer,
    extra_middleware: list[Any] | None = None,
) -> tuple[Any, set[str]]:
    """构建 Supervisor 及其三个领域子 Agent。

    返回 (supervisor_agent, subagent_tool_names)。
    """

    tools_by_name = {tool.name: tool for tool in tool_registry.get_tools()}
    business_tool_names: set[str] = set(tools_by_name)

    specialist_tools: list[Any] = []

    time_tools = [tools_by_name[n] for n in TIME_TOOL_NAMES if n in tools_by_name]
    if time_tools:
        specialist_tools.append(
            create_time_specialist_tool(
                model=model,
                time_tools=time_tools,
                tracer=tracer,
                business_tool_names=business_tool_names,
            )
        )

    file_tool = next((tools_by_name[n] for n in FILE_TOOL_NAMES if n in tools_by_name), None)
    if file_tool is not None:
        specialist_tools.append(
            create_file_specialist_tool(
                model=model,
                file_tool=file_tool,
                tracer=tracer,
                business_tool_names=business_tool_names,
            )
        )

    sql_tools = [tools_by_name[n] for n in SQL_TOOL_NAMES if n in tools_by_name]
    if sql_tools:
        specialist_tools.append(
            create_sql_specialist_tool(
                model=model,
                sql_tools=sql_tools,
                tracer=tracer,
                business_tool_names=business_tool_names,
            )
        )

    supervisor_agent = create_agent(
        model=model,
        tools=specialist_tools,
        system_prompt=load_prompt("supervisor"),
        checkpointer=checkpointer,
        middleware=list(extra_middleware or []),
        response_format=ToolStrategy(
            schema=AgentResponse,
            handle_errors=agent_response_handle_errors,
        ),
    )

    return supervisor_agent, set(SUBAGENT_TOOL_NAMES)
