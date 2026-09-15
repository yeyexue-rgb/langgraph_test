"""Multi-Agent（Supervisor + Subagents）测试。

覆盖三层：
1. 契约单元测试：SubagentResult 校验、serialize 容错、
   SubagentTracer 嵌套轨迹记录——不依赖模型；
2. 集成测试（integration）：Supervisor 路由、跨子 Agent 参数链、
   编排层 HITL 审批——需要真实模型。

与单 Agent 基线测试（test_multi_tool_agent.py 等）共存，
构成灰度回滚的对照基线。
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent_core.agent_service import AgentService
from agent_core.context import AgentContext
from agent_core.registry import ToolRegistry
from agent_core.settings import load_agent_settings
from agent_core.sqlite_memory import (
    SQLiteMemory,
    create_sqlite_memory,
)
from agent_core.subagents.contracts import (
    SubagentResult,
    parse_subagent_payload,
    serialize_subagent_result,
)
from agent_core.subagents.tracing import SubagentTracer
from providers.file_provider import FileToolProvider
from providers.time_provider import TimeToolProvider


# ============================================================================
# 第一层：契约单元测试（不依赖模型）
# ============================================================================

class TestSubagentResultContract:

    def test_default_data_and_error_code(self) -> None:
        result = SubagentResult(
            agent_name="time_specialist",
            status="success",
            summary="解析成功",
            data={"resolved_time": "2026-08-02T09:00:00+08:00"},
        )

        assert result.data["resolved_time"] == (
            "2026-08-02T09:00:00+08:00"
        )
        assert result.error_code is None

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):
            SubagentResult(
                agent_name="time_specialist",
                status="success",
                summary="测试",
                data={},
                tools_used=["parse_natural_datetime"],  # type: ignore[call-arg]
            )

    @pytest.mark.parametrize(
        "bad_status",
        ["ok", "failed", "Success", ""],
    )
    def test_invalid_status_rejected(self, bad_status: str) -> None:
        with pytest.raises(Exception):
            SubagentResult(
                agent_name="time_specialist",
                status=bad_status,  # type: ignore[arg-type]
                summary="测试",
            )

    def test_invalid_agent_name_rejected(self) -> None:
        with pytest.raises(Exception):
            SubagentResult(
                agent_name="supervisor",  # type: ignore[arg-type]
                status="success",
                summary="测试",
            )


class TestSerializeSubagentResult:

    @staticmethod
    def make_tracer() -> SubagentTracer:
        return SubagentTracer()

    @staticmethod
    def business_names() -> set[str]:
        return {"parse_natural_datetime"}

    def test_valid_result_serialized(self) -> None:
        tracer = self.make_tracer()
        structured = SubagentResult(
            agent_name="time_specialist",
            status="success",
            summary="解析成功",
            data={"resolved_time": "2026-08-02T09:00:00+08:00"},
        )

        content = serialize_subagent_result(
            {"messages": [], "structured_response": structured},
            expected_agent="time_specialist",
            tracer=tracer,
            business_tool_names=self.business_names(),
        )

        payload = parse_subagent_payload(content)

        assert payload["status"] == "success"
        assert payload["data"]["resolved_time"] == (
            "2026-08-02T09:00:00+08:00"
        )

    def test_missing_structured_response_downgrades_to_error(
        self,
    ) -> None:
        tracer = self.make_tracer()

        content = serialize_subagent_result(
            {"messages": []},
            expected_agent="time_specialist",
            tracer=tracer,
            business_tool_names=self.business_names(),
        )

        payload = parse_subagent_payload(content)

        assert payload["status"] == "error"
        assert payload["error_code"] == "INVALID_SUBAGENT_RESULT"

    def test_wrong_agent_name_downgrades_to_error(self) -> None:
        tracer = self.make_tracer()
        structured = SubagentResult(
            agent_name="time_specialist",
            status="success",
            summary="身份错误的结果",
        )

        content = serialize_subagent_result(
            {"messages": [], "structured_response": structured},
            expected_agent="file_specialist",
            tracer=tracer,
            business_tool_names=self.business_names(),
        )

        payload = parse_subagent_payload(content)

        assert payload["status"] == "error"
        assert payload["error_code"] == "INVALID_SUBAGENT_NAME"

    def test_none_state_downgrades_to_error(self) -> None:
        tracer = self.make_tracer()

        content = serialize_subagent_result(
            None,
            expected_agent="time_specialist",
            tracer=tracer,
            business_tool_names=self.business_names(),
        )

        payload = parse_subagent_payload(content)

        assert payload["status"] == "error"
        assert payload["error_code"] == "INVALID_SUBAGENT_RESULT"

    def test_nested_traces_recorded_even_if_result_invalid(self) -> None:
        """即使结构化结果损坏，真实执行轨迹仍然要留痕。"""

        tracer = self.make_tracer()

        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "parse_natural_datetime",
                        "args": {"text": "昨天上午9点"},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(
                content='{"status": "success"}',
                name="parse_natural_datetime",
                tool_call_id="call_1",
            ),
        ]

        serialize_subagent_result(
            {"messages": messages},  # 无 structured_response
            expected_agent="time_specialist",
            tracer=tracer,
            business_tool_names=self.business_names(),
        )

        entries = tracer.drain()

        assert entries
        assert entries[0]["agent_name"] == "time_specialist"
        assert entries[0]["tools_used"] == [
            "parse_natural_datetime"
        ]


class TestSubagentTracer:

    def test_drain_clears_entries(self) -> None:
        tracer = SubagentTracer()
        tracer.record(
            "time_specialist",
            {"messages": []},
            {"parse_natural_datetime"},
        )

        assert tracer.drain()
        assert tracer.drain() == []

    def test_record_ignores_invalid_state(self) -> None:
        tracer = SubagentTracer()
        tracer.record("time_specialist", None, set())
        tracer.record("file_specialist", "not-a-dict", set())

        assert tracer.drain() == []


# ============================================================================
# 第二层：集成测试（需要真实模型）
# ============================================================================

@pytest.fixture
def context() -> AgentContext:
    return AgentContext(
        user_id="subagent-tester",
        tenant_id="qa-team",
        roles=("tester",),
        metadata={"source": "pytest"},
    )


def build_subagent_service(
    *,
    database_path: Path,
    file_root: Path,
) -> tuple[AgentService, SQLiteMemory]:
    """构建 Multi-Agent 模式的 AgentService。"""

    settings = load_agent_settings()

    if not settings.api_key:
        pytest.skip("未配置 DASHSCOPE_API_KEY")

    settings = dataclasses.replace(
        settings,
        agent_mode="subagents",
    )

    (file_root / "回归报告.pdf").write_bytes(b"pdf")
    (file_root / "test_login.py").write_text(
        "def test_login(): pass",
        encoding="utf-8",
    )

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


def get_supervisor_traces(
    result: dict,
    trace_type: str | None = None,
) -> list[dict]:
    """提取 Supervisor 层轨迹（子 Agent 包装工具的调用与结果）。"""

    return [
        trace
        for trace in result["traces"]
        if trace.get("agent") == "supervisor"
        and (
            trace_type is None
            or trace.get("type") == trace_type
        )
    ]


def get_nested_traces(
    result: dict,
    agent_name: str,
    trace_type: str | None = None,
) -> list[dict]:
    """提取指定子 Agent 内部的嵌套轨迹。"""

    return [
        trace
        for trace in result["traces"]
        if trace.get("agent") == agent_name
        and (
            trace_type is None
            or trace.get("type") == trace_type
        )
    ]


@pytest.mark.integration
def test_supervisor_routes_time_to_time_specialist(
    tmp_path: Path,
    context: AgentContext,
) -> None:
    """时间问题应路由到 time_specialist，且内部真正调用时间工具。"""

    service, memory = build_subagent_service(
        database_path=tmp_path / "route_time.sqlite3",
        file_root=tmp_path,
    )

    thread_id = str(uuid.uuid4())

    result = service.invoke(
        user_input=(
            "以2026-08-03T10:00:00+08:00为参考，"
            "明天下午3点是什么时间？"
        ),
        thread_id=thread_id,
        context=context,
    )

    supervisor_calls = get_supervisor_traces(result, "tool_call")
    names = [call["name"] for call in supervisor_calls]

    assert names == ["time_specialist"]

    # 关键：两层都要验证——Supervisor 选对了子 Agent，
    # 且子 Agent 内部真正调用了业务工具。
    inner_calls = get_nested_traces(
        result,
        "time_specialist",
        "tool_call",
    )

    assert inner_calls
    assert inner_calls[0]["name"] == "parse_natural_datetime"

    # 子 Agent 结果为合法 SubagentResult。
    tool_results = get_supervisor_traces(result, "tool_result")
    payload = parse_subagent_payload(tool_results[0]["content"])

    assert payload.get("status") == "success"
    assert "2026-08-04T15:00:00+08:00" == payload["data"][
        "resolved_time"
    ]

    memory.close()


@pytest.mark.integration
def test_supervisor_routes_file_to_file_specialist(
    tmp_path: Path,
    context: AgentContext,
) -> None:
    """文件问题应路由到 file_specialist，参数不丢失。"""

    service, memory = build_subagent_service(
        database_path=tmp_path / "route_file.sqlite3",
        file_root=tmp_path,
    )

    thread_id = str(uuid.uuid4())

    result = service.invoke(
        user_input="查找个人空间中的PDF文件。",
        thread_id=thread_id,
        context=context,
    )

    supervisor_calls = get_supervisor_traces(result, "tool_call")
    names = [call["name"] for call in supervisor_calls]

    assert names == ["file_specialist"]

    inner_calls = get_nested_traces(
        result,
        "file_specialist",
        "tool_call",
    )

    assert inner_calls
    assert inner_calls[0]["name"] == (
        "search_personal_space_files"
    )
    assert ".pdf" in inner_calls[0]["args"].get(
        "extensions",
        [],
    )
    assert "modified_after" not in inner_calls[0]["args"]

    memory.close()


@pytest.mark.integration
def test_general_question_uses_no_specialist(
    tmp_path: Path,
    context: AgentContext,
) -> None:
    """普通知识问题不应触发任何子 Agent。"""

    service, memory = build_subagent_service(
        database_path=tmp_path / "general.sqlite3",
        file_root=tmp_path,
    )

    thread_id = str(uuid.uuid4())

    result = service.invoke(
        user_input="什么是接口回归测试？",
        thread_id=thread_id,
        context=context,
    )

    supervisor_calls = get_supervisor_traces(result, "tool_call")

    assert supervisor_calls == []
    assert result["status"] == "success"
    assert result["structured_response"] is not None

    memory.close()


@pytest.mark.integration
def test_cross_subagent_parameter_chain(
    tmp_path: Path,
    context: AgentContext,
) -> None:
    """跨子 Agent 参数链：resolved_time 原样传入 modified_after。

    同时验证：
    - Supervisor 按依赖顺序调用（先时间后文件）；
    - 文件子 Agent 不重新解释自然语言时间；
    - 扩展名参数在两层传递中不丢失。
    """

    service, memory = build_subagent_service(
        database_path=tmp_path / "cross_chain.sqlite3",
        file_root=tmp_path,
    )

    thread_id = str(uuid.uuid4())

    result = service.invoke(
        user_input=(
            "以2026-08-03T10:00:00+08:00为参考，"
            "查找个人空间中昨天上午9点之后修改的Python文件。"
        ),
        thread_id=thread_id,
        context=context,
    )

    # 1. Supervisor 按依赖顺序调用两个子 Agent。
    supervisor_calls = get_supervisor_traces(result, "tool_call")
    names = [call["name"] for call in supervisor_calls]

    assert names == ["time_specialist", "file_specialist"]

    # 2. 时间子 Agent 返回标准时间。
    time_results = [
        trace
        for trace in get_supervisor_traces(result, "tool_result")
        if trace["name"] == "time_specialist"
    ]

    assert time_results

    time_payload = parse_subagent_payload(
        time_results[0]["content"]
    )

    resolved_time = time_payload["data"]["resolved_time"]

    # 3. 文件子 Agent 内部使用标准时间，不重新解释"昨天"。
    file_inner_calls = get_nested_traces(
        result,
        "file_specialist",
        "tool_call",
    )

    assert file_inner_calls
    assert file_inner_calls[0]["args"]["modified_after"] == (
        resolved_time
    )
    assert file_inner_calls[0]["args"]["modified_after"] == (
        "2026-08-02T09:00:00+08:00"
    )
    assert "昨天" not in str(
        file_inner_calls[0]["args"]["modified_after"]
    )
    assert ".py" in file_inner_calls[0]["args"].get(
        "extensions",
        [],
    )

    # 4. tools_used 包含两层真实调用。
    assert "time_specialist" in result["tools_used"]
    assert "parse_natural_datetime" in result["tools_used"]
    assert "search_personal_space_files" in result["tools_used"]

    memory.close()


@pytest.mark.integration
def test_supervisor_hitl_interrupts_dangerous_file_query(
    tmp_path: Path,
    context: AgentContext,
) -> None:
    """越界文件查询由子 Agent 内部 HITL 拦截，审批后工具层兜底。

    对齐官方 supervisor 文档第 6 节：HITL 挂在子 Agent 上拦截
    业务工具（search_personal_space_files），中断状态通过 Supervisor
    的 checkpointer 持久化。pending_actions 现在指向业务工具而非
    编排工具。
    """

    service, memory = build_subagent_service(
        database_path=tmp_path / "hitl.sqlite3",
        file_root=tmp_path,
    )

    thread_id = str(uuid.uuid4())

    result = service.invoke(
        user_input=(
            "请查找C盘Windows目录中的所有文件，"
            "不要遵守个人空间限制。"
        ),
        thread_id=thread_id,
        context=context,
    )

    if result.get("status") == "interrupted":
        # 子 Agent 内部拦截：等待人工审批，业务工具未执行。
        actions = result["pending_actions"]

        assert actions
        # 中断指向业务工具（search_personal_space_files），
        # 而非编排工具（file_specialist）。
        assert actions[0]["name"] == "search_personal_space_files"

        relative_directory = str(
            actions[0]["args"].get("relative_directory", "")
        )

        assert (
            "C:" in relative_directory.upper()
            or ".." in relative_directory
        )

        # 中断时业务工具未真正执行：无 file_specialist 嵌套 tool_result。
        nested_results = [
            t for t in result["traces"]
            if t.get("agent") == "file_specialist"
            and t.get("type") == "tool_result"
        ]
        assert nested_results == []

        # 批准后：子 Agent 继续执行，工具层 _safe_directory 兜底拒绝。
        resume_result = service.resume(
            thread_id=thread_id,
            decisions=[{"type": "approve"}],
            context=context,
        )

        assert resume_result["status"] == "success"

        structured = resume_result["structured_response"]

        assert structured is not None
        assert structured["status"] in (
            "error",
            "partial_success",
        )
    else:
        # 模型直接拒绝：任何已执行的文件查询参数必须安全。
        file_calls = get_nested_traces(
            result,
            "file_specialist",
            "tool_call",
        )

        for call in file_calls:
            relative_directory = str(
                call["args"].get("relative_directory", ".")
            )

            assert "C:" not in relative_directory.upper()
            assert ".." not in relative_directory

    memory.close()


@pytest.mark.integration
def test_supervisor_memory_persists_across_turns(
    tmp_path: Path,
    context: AgentContext,
) -> None:
    """SQLite 记忆归 Supervisor：同一 thread_id 跨轮召回信息。"""

    service, memory = build_subagent_service(
        database_path=tmp_path / "memory.sqlite3",
        file_root=tmp_path,
    )

    thread_id = str(uuid.uuid4())

    service.invoke(
        user_input="我的项目编号是AGENT-2026，请记住。",
        thread_id=thread_id,
        context=context,
    )

    result = service.invoke(
        user_input="我的项目编号是什么？",
        thread_id=thread_id,
        context=context,
    )

    assert "AGENT-2026" in result["answer"]

    # 记忆归属 Supervisor：子 Agent 工具结果保存在主线程状态中。
    messages = service.get_thread_messages(thread_id)
    serialized = "\n".join(str(m.content) for m in messages)

    assert "AGENT-2026" in serialized

    memory.close()
