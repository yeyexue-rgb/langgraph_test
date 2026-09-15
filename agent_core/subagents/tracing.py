"""（补桥实现）轨迹提取：从 LangChain 消息轨迹中抽取业务工具调用。

契约：
- extract_business_traces(messages, business_tool_names) -> (traces, tools_used)
- trace 结构使用英文键：type/name/args/content/id
  * type="tool_call"：name/args/id
  * type="tool_result"：name/content/id
- 仅保留 business_tool_names 中的工具（过滤 AgentResponse 等结构化工具）
"""
from __future__ import annotations

from typing import Any


class SubagentTracer:
    """（补桥）子 Agent 轨迹记录器占位实现（single 模式不使用）。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def extract_business_traces(
    messages: list[Any],
    business_tool_names: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    traces: list[dict[str, Any]] = []
    tools_used: list[str] = []
    name_by_id: dict[str, str] = {}

    for message in messages:
        for tool_call in (getattr(message, "tool_calls", None) or []):
            name = tool_call.get("name")
            call_id = tool_call.get("id")
            if call_id:
                name_by_id[call_id] = name
            if business_tool_names and name not in business_tool_names:
                continue
            traces.append(
                {"type": "tool_call", "name": name, "args": tool_call.get("args"), "id": call_id}
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
