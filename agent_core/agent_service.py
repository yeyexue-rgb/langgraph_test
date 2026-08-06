"""Agent 服务层，页面只调用本层，不直接操作 LangChain Agent。

支持 SQLite 持久化短期记忆：
- 通过注入的 checkpointer（如 SqliteSaver）持久化会话状态；
- 相同 thread_id 可恢复历史消息并继续会话；
- 不同 thread_id 严格隔离；
- 应用重启后仍可恢复。

设计说明：
- 保留 settings / tool_registry 构造签名以兼容既有调用方与测试；
- checkpointer 可外部注入（测试用 SqliteSaver），
  默认使用 InMemorySaver 以保证无 SQLite 环境也能运行；
- trace 结构保持英文键（type/name/args/content/id），与既有测试一致；
- invoke 通过调用前的消息数量截取本轮新增消息，避免重复展示历史轨迹。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
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
        *,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        if not settings.api_key:
            raise ValueError(
                "未配置 DASHSCOPE_API_KEY，请在 .env 中配置。"
            )

        self.settings = settings
        self.tool_registry = tool_registry

        # Agent 必须长期复用，不能在每次请求时重新创建，
        # 否则会反复重建 checkpointer，也无法统一管理持久化连接。
        self.checkpointer: BaseCheckpointSaver = (
            checkpointer if checkpointer is not None
            else InMemorySaver()
        )

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

    @staticmethod
    def _build_config(thread_id: str) -> dict[str, Any]:
        """构造 LangGraph 运行配置，校验 thread_id。"""

        normalized_thread_id = (thread_id or "").strip()

        if not normalized_thread_id:
            raise ValueError("thread_id 不能为空")

        if len(normalized_thread_id) > 200:
            raise ValueError("thread_id 长度不能超过 200")

        return {
            "configurable": {
                "thread_id": normalized_thread_id,
            }
        }

    def invoke(
        self,
        user_input: str,
        thread_id: str,
        context: AgentContext | None = None,
    ) -> dict[str, Any]:
        """同步调用 Agent，返回归一化结果。

        相同 thread_id 会从 checkpointer 读取历史消息并继续该会话；
        不同 thread_id 视为新会话，不会继承其他线程信息。
        本轮只返回调用后新增的消息轨迹，避免重复展示历史工具调用。
        """

        normalized_input = (user_input or "").strip()

        if not normalized_input:
            raise ValueError("user_input 不能为空")

        config = self._build_config(thread_id)

        # 记录调用前的消息数，用于截取本轮新增消息。
        previous_messages = self.get_thread_messages(thread_id)
        previous_count = len(previous_messages)

        invoke_kwargs: dict[str, Any] = {"config": config}

        # context 仍兼容旧调用方；未传入时不传 context。
        if context is not None:
            invoke_kwargs["context"] = context

        result = self.agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": normalized_input,
                    }
                ]
            },
            **invoke_kwargs,
        )

        all_messages = result.get("messages", [])
        current_messages = all_messages[previous_count:]

        return self._normalize_result(
            all_messages,
            current_messages,
            thread_id,
            result,
        )

    def get_thread_messages(
        self,
        thread_id: str,
    ) -> list[Any]:
        """读取指定线程当前保存的消息（来自 checkpointer 快照）。

        用于断言短期记忆是否持久化、是否串线。线程不存在时返回空列表。
        """

        config = self._build_config(thread_id)
        snapshot = self.agent.get_state(config)

        if not snapshot or not snapshot.values:
            return []

        return list(snapshot.values.get("messages", []))

    @staticmethod
    def _normalize_result(
        all_messages: list[Any],
        current_messages: list[Any],
        thread_id: str,
        raw_result: dict[str, Any],
    ) -> dict[str, Any]:
        """提取最终文本答案、本轮轨迹与线程标识。"""

        final_text = ""
        traces: list[dict[str, Any]] = []

        # 轨迹只来自本轮新增消息，避免重复展示历史工具调用。
        for message in current_messages:
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
                                "id": tool_call.get("id", ""),
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
                        "id": message.tool_call_id,
                    }
                )

        # 兜底：若本轮未解析出最终文本（例如全是工具调用），
        # 取全部消息的最后一条 AI 文本。
        if not final_text and all_messages:
            last = all_messages[-1]
            if isinstance(last, AIMessage) and not getattr(
                last, "tool_calls", []
            ):
                final_text = AgentService._message_to_text(last)

        return {
            "answer": final_text,
            "thread_id": thread_id,
            "messages": all_messages,
            "traces": traces,
            "message_count": len(all_messages),
            "raw": raw_result,
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
                if isinstance(block, str):
                    text_parts.append(block)

                elif (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                ):
                    text_parts.append(block.get("text", ""))

            return "".join(text_parts)

        return str(content)
