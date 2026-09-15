"""结构化输出测试：Schema 校验、业务工具轨迹提取、历史回答恢复。

- Schema 与轨迹提取测试不调用真实模型，每次提交都跑；
- Agent 集成测试需要 DASHSCOPE_API_KEY。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from agent_core.agent_service import (
    AgentService,
    extract_business_traces,
)
from agent_core.context import AgentContext
from agent_core.registry import ToolRegistry
from agent_core.settings import load_agent_settings
from agent_core.sqlite_memory import (
    SQLiteMemory,
    create_sqlite_memory,
)
from agent_core.structured_output import AgentResponse
from providers.file_provider import FileToolProvider
from providers.time_provider import TimeToolProvider


# ============================================================================
# 1. Schema 单元测试（不调用真实模型）
# ============================================================================


def test_agent_response_accepts_valid_data() -> None:
    response = AgentResponse(
        status="success",
        answer="查询完成。",
        error_code=None,
        needs_human_review=False,
    )

    assert response.status == "success"
    assert response.answer == "查询完成。"
    assert response.error_code is None
    assert response.needs_human_review is False


def test_agent_response_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        AgentResponse(
            status="completed",
            answer="查询完成。",
        )


def test_agent_response_rejects_empty_answer() -> None:
    with pytest.raises(ValidationError):
        AgentResponse(
            status="success",
            answer="",
        )


def test_agent_response_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        AgentResponse(
            status="success",
            answer="查询完成。",
            unknown_field="unexpected",
        )


def test_agent_response_accepts_all_status_values() -> None:
    for status in (
        "success",
        "partial_success",
        "needs_clarification",
        "error",
    ):
        response = AgentResponse(
            status=status,
            answer="测试。",
        )
        assert response.status == status


def test_agent_response_error_code_optional() -> None:
    response = AgentResponse(
        status="error",
        answer="失败。",
        error_code="access_denied",
    )

    assert response.error_code == "access_denied"


# ============================================================================
# 2. 业务工具轨迹提取测试（不调用真实模型）
# ============================================================================

BUSINESS_TOOL_NAMES = {
    "parse_natural_datetime",
    "search_personal_space_files",
}


def test_extract_business_traces_filters_schema_tool() -> None:
    messages = [
        HumanMessage(content="查找 Python 文件。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_personal_space_files",
                    "args": {"extension": ".py"},
                    "id": "call-search",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status": "success"}',
            name="search_personal_space_files",
            tool_call_id="call-search",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "AgentResponse",
                    "args": {
                        "status": "success",
                        "answer": "查询完成。",
                        "error_code": None,
                        "needs_human_review": False,
                    },
                    "id": "call-response",
                    "type": "tool_call",
                }
            ],
        ),
    ]

    traces, tools_used = extract_business_traces(
        messages,
        BUSINESS_TOOL_NAMES,
    )

    assert tools_used == ["search_personal_space_files"]
    assert "AgentResponse" not in tools_used

    assert traces[1]["type"] == "tool_call"
    assert traces[1]["name"] == "search_personal_space_files"
    assert traces[2]["type"] == "tool_result"
    assert traces[2]["id"] == "call-search"


def test_extract_business_traces_preserves_order_and_duplicates() -> None:
    messages = [
        HumanMessage(content="多步骤任务。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "parse_natural_datetime",
                    "args": {"text": "昨天"},
                    "id": "call-time",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status": "success"}',
            name="parse_natural_datetime",
            tool_call_id="call-time",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_personal_space_files",
                    "args": {"extension": ".py"},
                    "id": "call-search-1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status": "success"}',
            name="search_personal_space_files",
            tool_call_id="call-search-1",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_personal_space_files",
                    "args": {"extension": ".py"},
                    "id": "call-search-2",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status": "success"}',
            name="search_personal_space_files",
            tool_call_id="call-search-2",
        ),
    ]

    traces, tools_used = extract_business_traces(
        messages,
        BUSINESS_TOOL_NAMES,
    )

    # 保留顺序与重复调用，便于发现无效调用或循环调用。
    assert tools_used == [
        "parse_natural_datetime",
        "search_personal_space_files",
        "search_personal_space_files",
    ]


def test_extract_business_traces_empty_messages() -> None:
    traces, tools_used = extract_business_traces(
        [],
        BUSINESS_TOOL_NAMES,
    )

    assert traces == []
    assert tools_used == []


# ============================================================================
# 3. Agent 集成测试（需要真实大模型）
# ============================================================================

pytestmark_integration = pytest.mark.integration


def build_structured_service(
    *,
    database_path: Path,
    file_root: Path,
) -> tuple[AgentService, SQLiteMemory]:
    """构建带临时文件目录与临时 SQLite 的 AgentService。"""

    settings = load_agent_settings()
    if not settings.api_key:
        pytest.skip("未配置 DASHSCOPE_API_KEY")

    registry = ToolRegistry()
    registry.register(TimeToolProvider())
    registry.register(
        FileToolProvider(root_directory=file_root)
    )

    memory = create_sqlite_memory(database_path)

    service = AgentService(
        settings=settings,
        tool_registry=registry,
        checkpointer=memory.checkpointer,
    )

    return service, memory


@pytest.fixture
def context() -> AgentContext:
    return AgentContext(
        user_id="structured-tester",
        tenant_id="qa-team",
        roles=("tester",),
        metadata={"source": "pytest"},
    )


@pytest.fixture
def service_with_files(
    tmp_path: Path,
) -> tuple[AgentService, SQLiteMemory]:
    (tmp_path / "test_login.py").write_text(
        "def test_login(): pass",
        encoding="utf-8",
    )

    return build_structured_service(
        database_path=tmp_path / "agent_memory.sqlite3",
        file_root=tmp_path,
    )


@pytest.mark.integration
def test_file_query_records_real_tool(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files

    result = service.invoke(
        user_input="查找名称包含 test 的 Python 文件。",
        thread_id="structured-file-test",
        context=context,
    )

    structured = result["structured_response"]

    assert structured["status"] == "success"
    assert "search_personal_space_files" in result["tools_used"]
    assert "AgentResponse" not in result["tools_used"]

    memory.close()


@pytest.mark.integration
def test_empty_result_is_success(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files

    result = service.invoke(
        user_input="查找名称包含 never-exists-9527 的文件。",
        thread_id="structured-empty-test",
        context=context,
    )

    structured = result["structured_response"]

    # 查询成功但结果为 0 条，仍然属于 success。
    assert structured["status"] == "success"
    assert structured["error_code"] is None

    memory.close()


@pytest.mark.integration
def test_access_denied_is_not_success(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files

    result = service.invoke(
        user_input="查询 C:\\Windows 中的文件。",
        thread_id="structured-security-test",
        context=context,
    )

    structured = result["structured_response"]

    # 越权访问被拒绝，核心任务未完成，应为 error。
    assert structured["status"] == "error"

    memory.close()


@pytest.mark.integration
def test_two_tool_workflow(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files

    result = service.invoke(
        user_input=(
            "以2026-08-11上午10点为参考，"
            "查找昨天上午9点以后修改的"
            "Python文件。"
        ),
        thread_id="structured-chain-test",
        context=context,
    )

    # 先解析时间，再查询文件，顺序保留。
    assert result["tools_used"] == [
        "parse_natural_datetime",
        "search_personal_space_files",
    ]

    memory.close()


@pytest.mark.integration
def test_structured_response_schema_valid(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    """Agent 返回的 structured_response 必须符合 AgentResponse Schema。"""

    service, memory = service_with_files

    result = service.invoke(
        user_input="查找个人空间中的 Python 文件。",
        thread_id="structured-schema-test",
        context=context,
    )

    structured = result["structured_response"]

    assert structured["status"] in {
        "success",
        "partial_success",
        "needs_clarification",
        "error",
    }
    assert isinstance(structured["answer"], str)
    assert len(structured["answer"]) > 0
    assert isinstance(structured["needs_human_review"], bool)

    memory.close()


@pytest.mark.integration
def test_layered_assertion_strategy(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    """分层断言：Schema → 工具选择 → 工具参数 → 状态 → 回答忠实性。"""

    service, memory = service_with_files

    result = service.invoke(
        user_input="查找名称包含 test 的 Python 文件。",
        thread_id="structured-layered-test",
        context=context,
    )

    # 第一层：Schema 合法
    structured = result["structured_response"]
    assert structured["status"] in {
        "success",
        "partial_success",
        "needs_clarification",
        "error",
    }

    # 第二层：调用了正确工具
    assert result["tools_used"] == [
        "search_personal_space_files"
    ]

    # 第三层：工具参数正确
    tool_calls = [
        trace
        for trace in result["traces"]
        if trace.get("type") == "tool_call"
    ]
    assert tool_calls
    args = tool_calls[0]["args"]
    assert ".py" in args.get("extensions", [])

    # 第四层：工具返回成功
    tool_results = [
        trace
        for trace in result["traces"]
        if trace.get("type") == "tool_result"
    ]
    assert tool_results
    assert "success" in tool_results[0]["content"]

    # 第五层：状态一致
    assert structured["status"] == "success"

    # 第六层：回答忠于事实
    assert "test_login.py" in result["answer"]

    memory.close()
