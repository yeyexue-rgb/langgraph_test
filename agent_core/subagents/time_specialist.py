"""时间领域子 Agent 及其 Supervisor 包装工具。

子 Agent 持有完整的 5 个时间工具，无 checkpointer、无记忆，
每次调用从干净上下文开始——这正是官方 Subagents 模式的默认行为，
适合无状态的领域解析任务。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool

from agent_core.subagents.contracts import (
    SubagentResult,
    serialize_subagent_result,
    subagent_handle_errors,
)
from agent_core.prompt_manager import load_prompt
from agent_core.subagents.tracing import SubagentTracer


def create_time_specialist_tool(
    *,
    model: Any,
    time_tools: list[Any],
    tracer: SubagentTracer,
    business_tool_names: set[str],
) -> Any:
    """构建时间子 Agent，并包装为 Supervisor 可调用的工具。

    model 与业务工具均复用现有实例，不重写任何确定性逻辑。
    """

    time_agent = create_agent(
        model=model,
        tools=time_tools,
        system_prompt=load_prompt("time_specialist"),
        response_format=ToolStrategy(
            schema=SubagentResult,
            handle_errors=subagent_handle_errors,
        ),
    )

    @tool(
        "time_specialist",
        description=(
            "处理一切时间相关的问题：解析自然语言日期时间、"
            "解析时间段（起止区间）、获取当前时间、日期加减、"
            "计算两个日期相差天数。当请求包含今天、明天、昨天、"
            "下周一、几天后、周末、现在几点、相差几天等表达时使用。"
        ),
    )
    def call_time_specialist(query: str) -> str:
        """解析或计算自然语言时间相关问题。"""

        state = time_agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "请处理以下时间相关问题："
                            f"{query}"
                        ),
                    }
                ]
            }
        )

        return serialize_subagent_result(
            state,
            expected_agent="time_specialist",
            tracer=tracer,
            business_tool_names=business_tool_names,
        )

    return call_time_specialist
