"""嵌套调用轨迹记录与业务轨迹提取。

extract_business_traces 从消息中提取白名单内业务工具的真实调用轨迹；
SubagentTracer 记录子 Agent 内部（Supervisor 视角不可见的）业务工具调用，
在 AgentService 归一化结果时合并进最终轨迹，形成嵌套可观测结构。
"""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def extract_business_traces(
    messages: list[Any],
    business_tool_names: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """从消息中提取真实执行的业务工具轨迹。

    - 业务工具名单使用白名单过滤（如 AgentResponse 结构化工具）；
    - tools_used 保留调用顺序与重复调用，不去重；
    - 保留 Tool Call ID 以便关联调用参数与返回结果。

    返回 (traces, tools_used)。
    """

    traces: list[dict[str, Any]] = []
    tools_used: list[str] = []

    for message in messages:
        if isinstance(message, HumanMessage):
            traces.append(
                {
                    "type": "human",
                    "content": message.content,
                }
            )
            continue

        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", [])

            for tool_call in tool_calls:
                tool_name = tool_call.get("name", "")

                if tool_name not in business_tool_names:
                    continue

                tools_used.append(tool_name)

                traces.append(
                    {
                        "type": "tool_call",
                        "name": tool_name,
                        "args": tool_call.get("args", {}),
                        "id": tool_call.get("id", ""),
                    }
                )

            continue

        if isinstance(message, ToolMessage):
            tool_name = message.name or ""

            if tool_name not in business_tool_names:
                continue

            traces.append(
                {
                    "type": "tool_result",
                    "name": tool_name,
                    "content": str(message.content),
                    "id": message.tool_call_id,
                }
            )

    return traces, tools_used


class SubagentTracer:
    """记录子 Agent 内部业务工具调用的嵌套轨迹。

    子 Agent 作为 Supervisor 的工具被调用时，其内部消息轨迹
    在 Supervisor 主消息中不可见。包装工具在每次调用结束后，
    将子 Agent 的内部轨迹记录到 Tracer；AgentService 在归一化
    结果时 drain 并合并，最终轨迹通过 "agent" 字段标识归属：

    - agent == "supervisor"：Supervisor 层的子 Agent 工具调用；
    - agent == "time_specialist" / "file_specialist"：子 Agent
      内部的业务工具调用。

    线程安全：内部加锁，兼容 Streamlit 多线程请求。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []

    def record(
        self,
        agent_name: str,
        state: dict[str, Any] | None,
        business_tool_names: set[str],
    ) -> None:
        """从子 Agent invoke 返回的状态中提取轨迹并记录。"""

        if not isinstance(state, dict):
            return

        messages = state.get("messages", [])

        traces, tools_used = extract_business_traces(
            messages,
            business_tool_names,
        )

        with self._lock:
            self._entries.append(
                {
                    "agent_name": agent_name,
                    "traces": traces,
                    "tools_used": tools_used,
                }
            )

    def drain(self) -> list[dict[str, Any]]:
        """取出并清空已记录的嵌套轨迹条目。"""

        with self._lock:
            entries = self._entries
            self._entries = []

        return entries
