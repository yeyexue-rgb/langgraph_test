"""Agent 层测试：验证 Agent 能正确识别意图并调用时间工具。

需要 DASHSCOPE_API_KEY，无 Key 时自动跳过。
"""

from __future__ import annotations

import json
import os

import pytest
from dotenv import load_dotenv

from agent_core.agent_service import AgentService
from agent_core.context import AgentContext
from agent_core.registry import ToolRegistry
from agent_core.settings import load_agent_settings
from providers.empty_provider import EmptyToolProvider
from providers.time_provider import TimeToolProvider

load_dotenv()


@pytest.fixture(scope="module")
def agent_service() -> AgentService:
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        pytest.skip("未配置 DASHSCOPE_API_KEY，跳过 Agent 测试")

    settings = load_agent_settings()
    registry = ToolRegistry()
    registry.register(EmptyToolProvider())
    registry.register(TimeToolProvider())

    return AgentService(
        settings=settings,
        tool_registry=registry,
    )


@pytest.fixture()
def context() -> AgentContext:
    return AgentContext(
        user_id="tester-001",
        tenant_id="qa-team",
        roles=("tester",),
    )


@pytest.fixture()
def thread_id() -> str:
    import uuid
    return str(uuid.uuid4())


class TestTimeAgent:
    """Agent 意图识别与工具调用。"""

    def test_agent_calls_time_tool(
        self,
        agent_service: AgentService,
        context: AgentContext,
        thread_id: str,
    ) -> None:
        result = agent_service.invoke(
            user_input='帮我把"明天下午3点"解析成标准时间',
            thread_id=thread_id,
            context=context,
        )

        traces = result["traces"]
        tool_calls = [
            t for t in traces if t["type"] == "tool_call"
        ]

        assert len(tool_calls) >= 1
        assert tool_calls[0]["name"] == "parse_natural_datetime"

        tool_results = [
            t for t in traces if t["type"] == "tool_result"
        ]
        assert len(tool_results) >= 1

        payload = json.loads(tool_results[0]["content"])
        assert payload["status"] == "success"

        answer = result["answer"]
        assert len(answer) > 0

    def test_agent_rejects_unsupported_expression(
        self,
        agent_service: AgentService,
        context: AgentContext,
        thread_id: str,
    ) -> None:
        result = agent_service.invoke(
            user_input="帮我解析'某个时候'",
            thread_id=thread_id,
            context=context,
        )

        traces = result["traces"]
        tool_results = [
            t for t in traces if t["type"] == "tool_result"
        ]

        if tool_results:
            payload = json.loads(tool_results[0]["content"])
            assert payload["status"] in ("unsupported", "error")
