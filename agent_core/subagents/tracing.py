"""子 Agent 轨迹记录与业务工具轨迹提取。

职责：
1. `extract_business_traces`：从 LangChain 消息中抽取业务工具调用轨迹
   （过滤结构化输出工具，如 AgentResponse / SubagentResult）；
2. `SubagentTracer`：记录各子 Agent 的嵌套轨迹，
   供 AgentService._merge_subagent_traces 合并进最终结果。

轨迹结构（英文键，与既有测试对齐）：
- {"type": "tool_call",   "name", "args", "id"}
- {"type": "tool_result", "name", "content", "id"}
"""
from __future__ import annotations

import threading
from typing import Any


def extract_business_traces(
    messages: list[Any],
    business_tool_names: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """从消息轨迹中提取业务工具调用（工具名白名单过滤）。

    返回 (traces, tools_used)；tools_used 保留调用顺序与重复调用。
    """

    traces: list[dict[str, Any]] = []
    tools_used: list[str] = []
    name_by_id: dict[str, str] = {}

    for message in messages:
        for tool_call in (getattr(message, "tool_calls", None) or []):
            name = tool_call.get("name")
            call_id = tool_call.get("id")

            if call_id:
                name_by_id[call_id] = name

            # 白名单过滤：结构化输出工具（AgentResponse/SubagentResult）不入轨迹
            if business_tool_names and name not in business_tool_names:
                continue

            traces.append(
                {
                    "type": "tool_call",
                    "name": name,
                    "args": tool_call.get("args"),
                    "id": call_id,
                }
            )
            if name:
                tools_used.append(name)

        if message.__class__.__name__ == "ToolMessage":
            name = getattr(message, "name", None) or name_by_id.get(
                getattr(message, "tool_call_id", None)
            )

            if business_tool_names and name not in business_tool_names:
                continue

            traces.append(
                {
                    "type": "tool_result",
                    "name": name,
                    "content": getattr(message, "content", ""),
                    "id": getattr(message, "tool_call_id", None),
                }
            )

    return traces, tools_used


class SubagentTracer:
    """记录子 Agent 内部嵌套轨迹（线程安全，可 drain 后合并）。

    使用方式：
        tracer.record("time_specialist", state, business_tool_names)
        entries = tracer.drain()   # [{"agent_name", "traces", "tools_used"}]
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(
        self,
        agent_name: str,
        state: Any,
        business_tool_names: set[str],
    ) -> None:
        """从子 Agent 的 invoke 状态中提取轨迹并暂存。"""

        messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
        traces, tools_used = extract_business_traces(list(messages or []), business_tool_names)

        with self._lock:
            self._entries.append(
                {
                    "agent_name": agent_name,
                    "traces": traces,
                    "tools_used": tools_used,
                }
            )

    def drain(self) -> list[dict[str, Any]]:
        """取出并清空已记录的轨迹（一次评测/一轮会话只合并一次）。"""

        with self._lock:
            entries, self._entries = self._entries, []
        return entries
