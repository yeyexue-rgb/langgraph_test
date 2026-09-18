"""Agent 服务层，页面只调用本层，不直接操作 LangChain Agent。

支持 SQLite 持久化短期记忆与结构化输出：
- 通过注入的 checkpointer（如 SqliteSaver）持久化会话状态；
- 相同 thread_id 可恢复历史消息并继续会话；
- 不同 thread_id 严格隔离；
- 应用重启后仍可恢复；
- 使用 ToolStrategy 强制 Agent 返回符合 AgentResponse 的结构化结果；
- 从真实消息轨迹中提取业务工具调用，过滤 AgentResponse 结构化工具；
- 本轮只返回当前轮新增消息轨迹，避免重复展示历史工具调用；
- 支持注入 HITL 中间件：危险工具调用触发人工审批中断，
  resume() 注入 approve / edit / reject 决策后恢复执行；
- 支持双架构模式（settings.agent_mode）：
  * single：单 Agent 直接持有业务工具（回归基线）；
  * subagents：Supervisor + 领域子 Agent（Multi-Agent 实验），
    外部接口完全不变，嵌套轨迹通过 SubagentTracer 合并，
    最终轨迹以 "agent" 字段标识归属（supervisor / 子 Agent 名）。

设计说明：
- 保留 settings / tool_registry 构造签名以兼容既有调用方与测试；
- checkpointer 可外部注入（测试用 SqliteSaver），
  默认使用 InMemorySaver 以保证无 SQLite 环境也能运行；
- middleware 可外部注入（如 HumanInTheLoopMiddleware），
  single 模式挂到单 Agent，subagents 模式追加到 Supervisor；
- trace 结构保持英文键（type/name/args/content/id），与既有测试一致。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_core.context import AgentContext
from agent_core.observability import (
    build_langfuse_handler,
    should_trace,
    trace_config,
)
from agent_core.observability import flush as flush_langfuse
from agent_core.registry import ToolRegistry
from agent_core.settings import AgentSettings
from agent_core.structured_output import (
    AgentResponse,
    agent_response_handle_errors,
)
from agent_core.subagents.tracing import (
    SubagentTracer,
    extract_business_traces,
)
from agent_core.supervisor import build_supervisor_agent


VALID_HITL_DECISION_TYPES = ("approve", "edit", "reject", "respond")

__all__ = [
    "AgentService",
    "extract_business_traces",
    "VALID_HITL_DECISION_TYPES",
]


class AgentService:
    """封装 LangChain Agent 的调用、结果归一化与轨迹提取。"""

    def __init__(
        self,
        settings: AgentSettings,
        tool_registry: ToolRegistry,
        *,
        checkpointer: BaseCheckpointSaver | None = None,
        middleware: list[Any] | None = None,
    ) -> None:
        if not settings.api_key:
            raise ValueError(
                "未配置 DASHSCOPE_API_KEY，请在 .env 中配置。"
            )

        self.settings = settings
        self.tool_registry = tool_registry
        self.middleware: list[Any] = list(middleware) if middleware else []
        self.agent_mode: str = settings.agent_mode

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

        tools = self.tool_registry.get_tools()

        # 业务工具名单来自 ToolRegistry，使用白名单过滤 AgentResponse。
        # 不通过排除固定名称判断，避免结构化响应类名变更时污染轨迹。
        self.business_tool_names: set[str] = {
            current_tool.name for current_tool in tools
        }

        if self.agent_mode == "subagents":
            # Multi-Agent 模式：Supervisor 持有子 Agent 包装工具，
            # 业务工具在子 Agent 内部执行；嵌套轨迹由 tracer 记录。
            self.subagent_tracer = SubagentTracer()

            self.agent, subagent_tool_names = build_supervisor_agent(
                model=self.model,
                tool_registry=self.tool_registry,
                checkpointer=self.checkpointer,
                tracer=self.subagent_tracer,
                extra_middleware=self.middleware,
            )

            # Supervisor 层轨迹白名单需包含子 Agent 工具名，
            # 否则编排调用（time_specialist / file_specialist）
            # 会被轨迹提取过滤掉。
            self.business_tool_names = set(self.business_tool_names) | set(
                subagent_tool_names
            )
        else:
            # 单 Agent 基线模式：直接持有业务工具。
            self.subagent_tracer = None  # type: ignore[assignment]

            self.agent = create_agent(
                model=self.model,
                tools=tools,
                system_prompt=settings.system_prompt,
                checkpointer=self.checkpointer,
                context_schema=AgentContext,
                middleware=self.middleware,
                response_format=ToolStrategy(
                    schema=AgentResponse,
                    handle_errors=agent_response_handle_errors,
                ),
            )

        # 可观测性（Langfuse）：未配置 LANGFUSE_* 时返回 None，
        # 后续 _attach_tracing 原样返回运行配置，行为与基线完全一致。
        self.langfuse_handler = build_langfuse_handler()

    def _attach_tracing(
        self,
        config: dict[str, Any],
        *,
        thread_id: str,
        context: AgentContext | None = None,
    ) -> dict[str, Any]:
        """按需把 Langfuse 回调与元数据合并进运行配置。

        - 未启用追踪 / 未命中采样 → 原样返回，零开销；
        - 已启用 → 追加 callbacks，并把 thread_id / user_id / tenant_id
          映射成 Langfuse 的 session / user / tags，便于按会话回放链路。
        """

        if self.langfuse_handler is None or not should_trace():
            return config

        tracing = trace_config(
            thread_id=thread_id,
            user_id=getattr(context, "user_id", None),
            tenant_id=getattr(context, "tenant_id", None),
            agent_mode=self.agent_mode,
        )

        if not tracing:
            return config

        merged = dict(config)
        merged["callbacks"] = list(config.get("callbacks", [])) + list(
            tracing.pop("callbacks")
        )
        merged.update(tracing)

        return merged

    def flush_tracing(self) -> None:
        """把缓冲的追踪数据推到 Langfuse（脚本/任务结束时调用）。"""

        if self.langfuse_handler is not None:
            flush_langfuse()

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
        """同步调用 Agent，返回归一化结构化结果。

        相同 thread_id 会从 checkpointer 读取历史消息并继续该会话；
        不同 thread_id 视为新会话，不会继承其他线程信息。
        本轮只返回当前轮新增消息轨迹，避免重复展示历史工具调用。
        """

        normalized_input = (user_input or "").strip()

        if not normalized_input:
            raise ValueError("user_input 不能为空")

        config = self._attach_tracing(
            self._build_config(thread_id),
            thread_id=thread_id,
            context=context,
        )

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

        # HITL 中间件触发人工审批时，invoke 结果携带 __interrupt__，
        # 此时不会产生 structured_response，走中断归一化分支。
        interrupts = self._extract_interrupts(result)

        if interrupts:
            return self._merge_subagent_traces(
                self._normalize_interrupted(
                    raw_result=result,
                    thread_id=thread_id,
                    pending_actions=self._extract_pending_actions(
                        interrupts,
                    ),
                )
            )

        return self._merge_subagent_traces(
            self._normalize_result(
                raw_result=result,
                thread_id=thread_id,
            )
        )

    def resume(
        self,
        thread_id: str,
        decisions: list[dict[str, Any]],
        context: AgentContext | None = None,
    ) -> dict[str, Any]:
        """注入人工决策，恢复被中断的 Agent 执行。

        decisions 必须与待审批操作一一对应且顺序一致，格式：
        - {"type": "approve"}
        - {"type": "edit", "edited_action": {"name": ..., "args": {...}}}
        - {"type": "reject", "message": "拒绝原因（可选）"}
        - {"type": "respond", "message": "人类回复"}（本项目未启用）

        恢复执行后可能再次触发新的审批中断（Agent 连续发起多个
        危险调用），返回结构与 invoke 一致，由调用方继续处理。
        """

        if not decisions:
            raise ValueError("decisions 不能为空")

        normalized_decisions = [
            self._validate_decision(decision)
            for decision in decisions
        ]

        config = self._attach_tracing(
            self._build_config(thread_id),
            thread_id=thread_id,
            context=context,
        )

        invoke_kwargs: dict[str, Any] = {"config": config}

        if context is not None:
            invoke_kwargs["context"] = context

        result = self.agent.invoke(
            Command(resume={"decisions": normalized_decisions}),
            **invoke_kwargs,
        )

        interrupts = self._extract_interrupts(result)

        if interrupts:
            return self._merge_subagent_traces(
                self._normalize_interrupted(
                    raw_result=result,
                    thread_id=thread_id,
                    pending_actions=self._extract_pending_actions(
                        interrupts,
                    ),
                )
            )

        return self._merge_subagent_traces(
            self._normalize_result(
                raw_result=result,
                thread_id=thread_id,
            )
        )

    def _merge_subagent_traces(
        self,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """将子 Agent 内部嵌套轨迹合并进最终结果。

        仅 subagents 模式生效：
        - Supervisor 层轨迹补 "agent": "supervisor" 标识；
        - 子 Agent 内部业务工具轨迹附加在轨迹末尾，
          以 "agent": 子 Agent 名标识归属；
        - tools_used 合并子 Agent 内部真实调用的业务工具名。
        """

        if self.agent_mode != "subagents":
            return result

        tracer = self.subagent_tracer

        if tracer is None:
            return result

        entries = tracer.drain()

        if not entries:
            return result

        for trace in result.get("traces", []):
            trace.setdefault("agent", "supervisor")

        nested_traces: list[dict[str, Any]] = []
        nested_tools: list[str] = []

        for entry in entries:
            for trace in entry.get("traces", []):
                nested_trace = dict(trace)
                nested_trace["agent"] = entry.get("agent_name", "")
                nested_traces.append(nested_trace)

            nested_tools.extend(entry.get("tools_used", []))

        result["traces"] = list(result.get("traces", [])) + nested_traces
        result["tools_used"] = (
            list(result.get("tools_used", [])) + nested_tools
        )

        return result

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
    def _extract_state(raw_result: Any) -> dict[str, Any]:
        """从 invoke 结果中提取状态 dict，兼容 v1 dict 与 GraphOutput。"""

        if isinstance(raw_result, dict):
            return raw_result

        value = getattr(raw_result, "value", None)
        if isinstance(value, dict):
            return value

        return {}

    @staticmethod
    def _extract_interrupts(raw_result: Any) -> list[Any]:
        """提取 invoke 结果中的中断列表。

        v1 模式结果为 dict，中断在 "__interrupt__" 键下；
        v2 GraphOutput 提供 .interrupts 属性。
        """

        if isinstance(raw_result, dict):
            interrupts = raw_result.get("__interrupt__") or ()
        else:
            interrupts = getattr(raw_result, "interrupts", None) or ()

        if isinstance(interrupts, (list, tuple)):
            return [item for item in interrupts if item is not None]

        return [interrupts] if interrupts else []

    @staticmethod
    def _extract_pending_actions(
        interrupts: list[Any],
    ) -> list[dict[str, Any]]:
        """从 HITLRequest 中提取待审批操作，供页面与测试展示。"""

        actions: list[dict[str, Any]] = []

        for interrupt in interrupts:
            value = getattr(interrupt, "value", interrupt)

            if not isinstance(value, dict):
                continue

            allowed_by_tool = {
                str(config.get("action_name", "")): list(
                    config.get("allowed_decisions", [])
                )
                for config in value.get("review_configs", [])
                if isinstance(config, dict)
            }

            for action_request in value.get("action_requests", []):
                if not isinstance(action_request, dict):
                    continue

                tool_name = str(action_request.get("name", ""))

                actions.append(
                    {
                        "name": tool_name,
                        "args": action_request.get("args", {}) or {},
                        "description": str(
                            action_request.get("description", "")
                        ),
                        "allowed_decisions": allowed_by_tool.get(
                            tool_name,
                            [],
                        ),
                    }
                )

        return actions

    @staticmethod
    def _validate_decision(decision: Any) -> dict[str, Any]:
        """校验并归一化单条人工决策，防止非法决策注入中间件。"""

        if not isinstance(decision, dict):
            raise ValueError(f"决策必须是字典：{decision!r}")

        decision_type = decision.get("type")

        if decision_type not in VALID_HITL_DECISION_TYPES:
            raise ValueError(
                "决策 type 必须是 "
                f"{VALID_HITL_DECISION_TYPES} 之一：{decision_type!r}"
            )

        if decision_type == "edit":
            edited_action = decision.get("edited_action")

            if (
                not isinstance(edited_action, dict)
                or "name" not in edited_action
            ):
                raise ValueError(
                    "edit 决策必须包含 edited_action："
                    "{'name': ..., 'args': ...}"
                )

        if decision_type == "respond" and not str(
            decision.get("message") or ""
        ).strip():
            raise ValueError("respond 决策必须包含非空 message")

        normalized: dict[str, Any] = {"type": decision_type}

        message = decision.get("message")

        if message:
            normalized["message"] = message

        if decision_type == "edit":
            normalized["edited_action"] = decision["edited_action"]

        return normalized

    def _normalize_interrupted(
        self,
        *,
        raw_result: dict[str, Any],
        thread_id: str,
        pending_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """归一化被 HITL 中断的结果。

        中断时 Agent 未运行到结构化输出节点，structured_response
        为 None；被拦截的 tool_call 仍会出现在本轮轨迹中，
        但不会有对应的 tool_result（未执行）。
        """

        all_messages = self._extract_state(raw_result).get(
            "messages",
            [],
        )

        current_turn_start = 0

        for index in range(
            len(all_messages) - 1,
            -1,
            -1,
        ):
            if isinstance(all_messages[index], HumanMessage):
                current_turn_start = index
                break

        current_messages = all_messages[current_turn_start:]

        traces, tools_used = extract_business_traces(
            current_messages,
            self.business_tool_names,
        )

        return {
            "status": "interrupted",
            "answer": "",
            "structured_response": None,
            "tools_used": tools_used,
            "thread_id": thread_id,
            "pending_actions": pending_actions,
            "messages": all_messages,
            "traces": traces,
            "message_count": len(all_messages),
            "raw": raw_result,
        }

    def _normalize_result(
        self,
        *,
        raw_result: dict[str, Any],
        thread_id: str,
    ) -> dict[str, Any]:
        """将 Agent 原始结果转换为页面和测试可使用的结构。

        - 从 structured_response 读取最终结论；
        - 只提取当前轮（最后一条 HumanMessage 之后）的工具轨迹，
          避免混入前几轮调用过的工具；
        - tools_used 来自真实 tool_calls，过滤 AgentResponse；
        - 保留工具调用顺序与重复调用。
        """

        all_messages = self._extract_state(raw_result).get(
            "messages",
            [],
        )

        # 找到最后一条 HumanMessage，作为当前轮的起点。
        current_turn_start = 0

        for index in range(
            len(all_messages) - 1,
            -1,
            -1,
        ):
            if isinstance(all_messages[index], HumanMessage):
                current_turn_start = index
                break

        current_messages = all_messages[current_turn_start:]

        structured = self._extract_state(raw_result).get(
            "structured_response",
        )

        if not isinstance(structured, AgentResponse):
            raise RuntimeError(
                "Agent 未返回有效的结构化响应"
            )

        traces, tools_used = extract_business_traces(
            current_messages,
            self.business_tool_names,
        )

        structured_data = structured.model_dump()

        return {
            "status": "success",
            "answer": structured.answer,
            "structured_response": structured_data,
            "tools_used": tools_used,
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
