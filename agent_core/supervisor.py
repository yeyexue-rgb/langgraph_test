"""Supervisor 主协调 Agent 构建。

架构：
    AgentService（外部接口不变）
        ↓
    Supervisor Agent（SQLite 记忆、AgentResponse）
        ├── time_specialist 工具 → 时间子 Agent → 时间工具矩阵（5 个）
        └── file_specialist 工具 → 文件子 Agent
                                    ├── HITL 中间件（拦截 search_personal_space_files）
                                    └── search_personal_space_files

关键决策（对齐官方 supervisor 文档第 6 节）：
1. SQLite Checkpointer 只挂 Supervisor——子 Agent 无独立 checkpointer，
   但子 Agent 作为 Supervisor 的工具被调用，其中断状态通过 Supervisor
   的 checkpointer 持久化，重启后可恢复；
2. HITL 审批挂在 file_specialist 子 Agent 内部，拦截业务工具
   search_personal_space_files 的越界调用——审批粒度是业务工具
   而非编排调用，与官方 create_calendar_event / send_email 拦截模式一致；
3. 工具层安全边界（_safe_directory）原样保留作为最终防线；
4. Supervisor 不直接持有业务工具——避免出现
   "Supervisor → 业务工具" 与 "Supervisor → 子Agent → 业务工具"
   双入口，保证路由测试与权限边界的唯一性。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

from agent_core.context import AgentContext
from agent_core.prompt_manager import load_prompt
from agent_core.structured_output import AgentResponse
from agent_core.subagents.file_specialist import (
    create_file_specialist_tool,
)
from agent_core.subagents.sql_specialist import (
    create_sql_specialist_tool,
)
from agent_core.subagents.time_specialist import (
    create_time_specialist_tool,
)
from agent_core.subagents.tracing import SubagentTracer


TIME_TOOL_NAMES = [
    "parse_natural_datetime",
    "parse_time_range",
    "get_current_time",
    "date_add",
    "date_diff",
]
FILE_TOOL_NAME = "search_personal_space_files"
SQL_TOOL_NAMES = [
    "sql_db_list_tables",
    "sql_db_schema",
    "sql_db_query",
    "sql_db_query_checker",
]

SUBAGENT_TOOL_NAMES = [
    "time_specialist",
    "file_specialist",
    "sql_specialist",
]


def build_supervisor_agent(
    *,
    model: Any,
    tool_registry: Any,
    checkpointer: Any,
    tracer: SubagentTracer,
    extra_middleware: list[Any] | None = None,
) -> tuple[Any, list[str]]:
    """构建 Supervisor Agent，返回 (agent, subagent_tool_names)。

    - 业务工具来自 ToolRegistry（不重写、不复制实现）；
    - tracer 由调用方（AgentService）持有，跨 invoke 复用；
    - extra_middleware 追加到 Supervisor（如外部注入的监控）。

    HITL 现在挂在 file_specialist 子 Agent 内部（拦截业务工具），
    Supervisor 自身只保留 checkpointer 用于子 Agent 中断的暂停/恢复。
    """

    tools = tool_registry.get_tools()
    tools_by_name = {current.name: current for current in tools}

    time_tools = [
        tools_by_name[name]
        for name in TIME_TOOL_NAMES
        if name in tools_by_name
    ]

    if len(time_tools) != len(TIME_TOOL_NAMES):
        missing = set(TIME_TOOL_NAMES) - set(tools_by_name)
        raise ValueError(
            f"Multi-Agent 模式需要注册时间工具：{missing}"
        )

    if FILE_TOOL_NAME not in tools_by_name:
        raise ValueError(
            f"Multi-Agent 模式需要注册 {FILE_TOOL_NAME} 工具。"
        )

    sql_tools = [
        tools_by_name[name]
        for name in SQL_TOOL_NAMES
        if name in tools_by_name
    ]

    if len(sql_tools) != len(SQL_TOOL_NAMES):
        missing = set(SQL_TOOL_NAMES) - set(tools_by_name)
        raise ValueError(
            f"Multi-Agent 模式需要注册 SQL 工具：{missing}"
        )

    business_tool_names = set(tools_by_name)

    time_specialist_tool = create_time_specialist_tool(
        model=model,
        time_tools=time_tools,
        tracer=tracer,
        business_tool_names=business_tool_names,
    )

    file_specialist_tool = create_file_specialist_tool(
        model=model,
        file_tool=tools_by_name[FILE_TOOL_NAME],
        tracer=tracer,
        business_tool_names=business_tool_names,
    )

    sql_specialist_tool = create_sql_specialist_tool(
        model=model,
        sql_tools=sql_tools,
        tracer=tracer,
        business_tool_names=business_tool_names,
    )

    # Supervisor 自身不再挂 HITL——审批已下移到 file_specialist 子 Agent
    # 内部，拦截业务工具 search_personal_space_files。中断状态通过
    # Supervisor 的 checkpointer 持久化（子 Agent 作为 Supervisor 的
    # 工具被调用，其中断发生在 Supervisor 的执行流内）。
    middleware: list[Any] = []

    if extra_middleware:
        middleware.extend(extra_middleware)

    supervisor = create_agent(
        model=model,
        tools=[
            time_specialist_tool,
            file_specialist_tool,
            sql_specialist_tool,
        ],
        system_prompt=load_prompt("supervisor"),
        checkpointer=checkpointer,
        context_schema=AgentContext,
        middleware=middleware,
        response_format=ToolStrategy(
            schema=AgentResponse,
            handle_errors=(
                "最终结果必须符合 AgentResponse。"
                "status 必须使用指定枚举值；answer 不能为空；"
                "没有明确错误代码时，error_code 必须为 null；"
                "不得编造子 Agent 结果或错误代码。"
            ),
        ),
    )

    return supervisor, SUBAGENT_TOOL_NAMES
