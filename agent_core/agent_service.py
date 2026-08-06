"""Agent 服务层，页面只调用本层，不直接操作 LangChain Agent。"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from agent_core.context import AgentContext
from agent_core.registry import ToolRegistry
from agent_core.settings import AgentSettings


class AgentService:
    """封装 LangChain Agent 的调用、结果归一化与轨迹提取。"""

    def __init__(
        self,
        settings: AgentSettings,
        tool_registry: ToolRegistry,
    ) -> None:
        if not settings.api_key:
            raise ValueError(
                "未配置 DASHSCOPE_API_KEY，请在 .env 中配置。"
            )

        self.settings = settings
        self.tool_registry = tool_registry
        self.checkpointer = InMemorySaver()

        self.model = ChatOpenAI(
            model=settings.model_name,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=settings.temperature,
            streaming=False,
            # 当前版本先关闭 Thinking，减少兼容 OpenAI Tool Calling
            # 接口时的额外复杂度。后续可按模型能力单独开放。
            extra_body={"enable_thinking": False},
        )

        self.agent = create_agent(
            model=self.model,
            tools=self.tool_registry.get_tools(),
            system_prompt=settings.system_prompt,
            checkpointer=self.checkpointer,
            context_schema=AgentContext,
        )

    def invoke(
        self,
        user_input: str,
        thread_id: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        """同步调用 Agent，返回归一化结果。"""

        result = self.agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": user_input,
                    }
                ]
            },
            config={
                "configurable": {
                    "thread_id": thread_id,
                }
            },
            context=context,
        )

        return self._normalize_result(result)

    @staticmethod
    def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
        """提取最终文本答案与执行轨迹。"""

        messages = result.get("messages", [])
        final_text = ""
        traces: list[dict[str, Any]] = []

        for message in messages:
            if isinstance(message, HumanMessage):
                traces.append(
                    {
                        "type": "human",
                        "content": message.content,
                    }
                )

            elif isinstance(message, AIMessage):
                tool_calls = getattr(message, "tool_calls", [])

                if tool_calls:
                    for tool_call in tool_calls:
                        traces.append(
                            {
                                "type": "tool_call",
                                "name": tool_call.get("name", ""),
                                "args": tool_call.get("args", {}),
                            }
                        )
                else:
                    final_text = AgentService._message_to_text(message)

            elif isinstance(message, ToolMessage):
                traces.append(
                    {
                        "type": "tool_result",
                        "name": message.name or "",
                        "content": AgentService._message_to_text(message),
                    }
                )

        return {
            "answer": final_text,
            "messages": messages,
            "traces": traces,
            "raw": result,
        }

    @staticmethod
    def _message_to_text(message: Any) -> str:
        """将消息内容转换为纯文本，兼容字符串与分块列表。"""

        content = getattr(message, "content", "")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: list[str] = []

            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                ):
                    text_parts.append(block.get("text", ""))

            return "".join(text_parts)

        return str(content)
