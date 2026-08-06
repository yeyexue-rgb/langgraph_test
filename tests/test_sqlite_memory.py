"""SQLite 短期记忆测试：线程隔离、thread_id 校验、重启恢复、多轮继承、跨轮工具链。

与现有 AgentService trace 结构对齐（英文键 type/name/args/content/id）。
- 标注 integration 的用例需要 DASHSCOPE_API_KEY；
- 未标注 integration 的持久化用例不调用真实模型，每次提交都跑。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from agent_core.agent_service import AgentService
from agent_core.context import AgentContext
from agent_core.registry import ToolRegistry
from agent_core.settings import load_agent_settings
from agent_core.sqlite_memory import (
    SQLiteMemory,
    create_sqlite_memory,
)
from providers.file_provider import FileToolProvider
from providers.time_provider import TimeToolProvider


# ============================================================================
# 公共工具
# ============================================================================

def build_test_service(
    *,
    database_path: Path,
) -> tuple[AgentService, SQLiteMemory]:
    """基于临时 SQLite 构建 AgentService，用于持久化测试。"""

    settings = load_agent_settings()
    if not settings.api_key:
        pytest.skip("未配置 DASHSCOPE_API_KEY")

    registry = ToolRegistry()
    registry.register(TimeToolProvider())
    registry.register(FileToolProvider())

    memory = create_sqlite_memory(database_path)

    service = AgentService(
        settings=settings,
        tool_registry=registry,
        checkpointer=memory.checkpointer,
    )

    return service, memory


def build_test_service_with_files(
    *,
    database_path: Path,
    file_root: Path,
) -> tuple[AgentService, SQLiteMemory]:
    """构建带临时文件目录的 AgentService，用于文件工具多轮测试。"""

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


def get_tool_calls(result: dict) -> list[dict]:
    """提取模型发起的工具调用轨迹。"""

    return [
        trace
        for trace in result["traces"]
        if trace.get("type") == "tool_call"
    ]


def write_message(
    agent: Any,
    thread_id: str,
    text: str,
) -> None:
    """向指定线程写入一条 HumanMessage（不经过模型）。"""

    config = {
        "configurable": {"thread_id": thread_id},
    }

    agent.agent.invoke(
        {
            "messages": [
                HumanMessage(content=text),
            ]
        },
        config=config,
    )


# ============================================================================
# 持久化单元测试（不调用真实模型）
# ============================================================================

class TestSQLitePersistence:
    """SQLite 持久化基础行为，每次提交都运行。"""

    def test_thread_id_must_not_be_empty(
        self,
        tmp_path: Path,
    ) -> None:
        service, memory = build_test_service(
            database_path=tmp_path / "agent_memory.sqlite3",
        )

        with pytest.raises(ValueError):
            service.invoke(
                user_input="测试",
                thread_id="",
            )

        with pytest.raises(ValueError):
            service.invoke(
                user_input="测试",
                thread_id="   ",
            )

        with pytest.raises(ValueError):
            service.get_thread_messages("")

        memory.close()

    def test_thread_id_length_limit(
        self,
        tmp_path: Path,
    ) -> None:
        service, memory = build_test_service(
            database_path=tmp_path / "agent_memory.sqlite3",
        )

        with pytest.raises(ValueError):
            service.invoke(
                user_input="测试",
                thread_id="x" * 201,
            )

        memory.close()

    def test_different_threads_are_isolated(
        self,
        tmp_path: Path,
    ) -> None:
        service, memory = build_test_service(
            database_path=tmp_path / "agent_memory.sqlite3",
        )

        write_message(service, "thread-a", "A线程机密：SECRET-A-001")
        write_message(service, "thread-b", "这是B线程。")

        messages_b = service.get_thread_messages("thread-b")
        serialized_b = "\n".join(
            str(m.content) for m in messages_b
        )

        assert "SECRET-A-001" not in serialized_b
        assert "这是B线程" in serialized_b

        messages_a = service.get_thread_messages("thread-a")
        serialized_a = "\n".join(
            str(m.content) for m in messages_a
        )

        assert "SECRET-A-001" in serialized_a
        assert "这是B线程" not in serialized_a

        memory.close()

    def test_unknown_thread_returns_empty(
        self,
        tmp_path: Path,
    ) -> None:
        service, memory = build_test_service(
            database_path=tmp_path / "agent_memory.sqlite3",
        )

        assert service.get_thread_messages("never-exists") == []

        memory.close()

    def test_new_thread_does_not_read_old_data(
        self,
        tmp_path: Path,
    ) -> None:
        service, memory = build_test_service(
            database_path=tmp_path / "agent_memory.sqlite3",
        )

        write_message(service, "old-thread", "旧数据：OLD-001")
        write_message(service, "new-thread", "新数据：NEW-001")

        new_messages = service.get_thread_messages("new-thread")
        serialized = "\n".join(
            str(m.content) for m in new_messages
        )

        assert "OLD-001" not in serialized
        assert "NEW-001" in serialized

        memory.close()

    def test_database_directory_auto_created(
        self,
        tmp_path: Path,
    ) -> None:
        nested = tmp_path / "nested" / "deep" / "dir"
        db_path = nested / "agent_memory.sqlite3"

        assert not nested.exists()

        _, memory = build_test_service(database_path=db_path)

        assert nested.exists()
        assert db_path.exists()

        memory.close()

    def test_sqlite_restores_thread_after_restart(
        self,
        tmp_path: Path,
    ) -> None:
        database_path = tmp_path / "restart_memory.sqlite3"
        thread_id = "restart-test-thread"

        first_service, first_memory = build_test_service(
            database_path=database_path,
        )

        write_message(
            first_service,
            thread_id,
            "项目编号是SQLITE-9527。",
        )

        first_memory.close()

        # 模拟应用重启：重新建立连接、Checkpointer 和 Agent。
        second_service, second_memory = build_test_service(
            database_path=database_path,
        )

        messages = second_service.get_thread_messages(thread_id)

        serialized = "\n".join(
            str(m.content) for m in messages
        )

        assert "SQLITE-9527" in serialized

        second_memory.close()


# ============================================================================
# 集成测试（需要真实大模型）
# ============================================================================

@pytest.fixture
def context() -> AgentContext:
    return AgentContext(
        user_id="memory-tester",
        tenant_id="qa-team",
        roles=("tester",),
        metadata={"source": "pytest"},
    )


@pytest.fixture
def service_with_files(
    tmp_path: Path,
) -> tuple[AgentService, SQLiteMemory]:
    """构建带临时文件目录与临时 SQLite 的 AgentService。"""

    settings = load_agent_settings()
    if not settings.api_key:
        pytest.skip("未配置 DASHSCOPE_API_KEY")

    # 为文件工具准备测试文件
    (tmp_path / "test_login.py").write_text(
        "def test_login(): pass",
        encoding="utf-8",
    )

    return build_test_service_with_files(
        database_path=tmp_path / "agent_memory.sqlite3",
        file_root=tmp_path,
    )


@pytest.mark.integration
def test_same_thread_saves_messages(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files
    thread_id = str(uuid.uuid4())

    service.invoke(
        user_input="项目编号是AGENT-2026。",
        thread_id=thread_id,
        context=context,
    )

    service.invoke(
        user_input="请重复项目编号。",
        thread_id=thread_id,
        context=context,
    )

    messages = service.get_thread_messages(thread_id)
    serialized = "\n".join(
        str(m.content) for m in messages
    )

    assert "AGENT-2026" in serialized
    assert "请重复项目编号" in serialized

    memory.close()


@pytest.mark.integration
def test_same_thread_recalls_information(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files
    thread_id = str(uuid.uuid4())

    service.invoke(
        user_input="我的测试编号是QA-9527，请记住。",
        thread_id=thread_id,
        context=context,
    )

    result = service.invoke(
        user_input="我的测试编号是什么？",
        thread_id=thread_id,
        context=context,
    )

    assert "QA-9527" in result["answer"]

    memory.close()


@pytest.mark.integration
def test_different_threads_are_isolated(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files
    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())

    service.invoke(
        user_input="我的机密编号是SECRET-A-001。",
        thread_id=thread_a,
        context=context,
    )

    result = service.invoke(
        user_input="我的机密编号是什么？",
        thread_id=thread_b,
        context=context,
    )

    assert "SECRET-A-001" not in result["answer"]

    messages_b = service.get_thread_messages(thread_b)
    serialized = "\n".join(
        str(m.content) for m in messages_b
    )

    assert "SECRET-A-001" not in serialized

    memory.close()


@pytest.mark.integration
def test_follow_up_inherits_file_condition(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files
    thread_id = str(uuid.uuid4())

    service.invoke(
        user_input="查找个人空间中的Python文件。",
        thread_id=thread_id,
        context=context,
    )

    result = service.invoke(
        user_input="只看文件名包含test的。",
        thread_id=thread_id,
        context=context,
    )

    tool_calls = get_tool_calls(result)

    assert tool_calls
    assert tool_calls[-1]["name"] == (
        "search_personal_space_files"
    )

    arguments = tool_calls[-1]["args"]

    assert arguments["keyword"].lower() == "test"
    assert ".py" in arguments.get("extensions", [])

    memory.close()


@pytest.mark.integration
def test_cross_turn_tool_chain(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    service, memory = service_with_files
    thread_id = str(uuid.uuid4())

    first_result = service.invoke(
        user_input=(
            "以2026-08-03T10:00:00+08:00为参考，"
            "昨天上午9点是什么时间？"
        ),
        thread_id=thread_id,
        context=context,
    )

    assert "2026-08-02" in first_result["answer"]
    assert "09:00" in first_result["answer"]

    second_result = service.invoke(
        user_input=(
            "查找个人空间中这个时间之后修改的"
            "Python文件。"
        ),
        thread_id=thread_id,
        context=context,
    )

    tool_calls = get_tool_calls(second_result)

    assert tool_calls[-1]["name"] == (
        "search_personal_space_files"
    )

    arguments = tool_calls[-1]["args"]

    assert ".py" in arguments["extensions"]
    assert arguments["modified_after"] == (
        "2026-08-02T09:00:00+08:00"
    )

    memory.close()


@pytest.mark.integration
def test_new_thread_does_not_reference_old_tool_result(
    service_with_files: tuple[AgentService, SQLiteMemory],
    context: AgentContext,
) -> None:
    """新线程询问“这个时间”应要求补充，不应使用旧线程工具结果。"""

    service, memory = service_with_files
    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())

    service.invoke(
        user_input=(
            "以2026-08-03T10:00:00+08:00为参考，"
            "昨天上午9点是什么时间？"
        ),
        thread_id=thread_a,
        context=context,
    )

    result = service.invoke(
        user_input="查找个人空间中这个时间之后修改的Python文件。",
        thread_id=thread_b,
        context=context,
    )

    tool_calls = get_tool_calls(result)

    # 新线程不应有带 modified_after 的文件调用（缺少历史时间）
    file_calls_with_time = [
        call for call in tool_calls
        if call["name"] == "search_personal_space_files"
        and "modified_after" in call["args"]
    ]

    assert file_calls_with_time == []

    memory.close()


@pytest.mark.integration
def test_agent_recalls_after_restart(
    tmp_path: Path,
    context: AgentContext,
) -> None:
    """应用重启后，使用相同 thread_id 仍可召回历史信息。"""

    database_path = tmp_path / "restart_recall.sqlite3"
    thread_id = "restart-recall-thread"

    first_service, first_memory = build_test_service(
        database_path=database_path,
    )

    first_service.invoke(
        user_input="我的编号是RESTART-2026。",
        thread_id=thread_id,
        context=context,
    )

    first_memory.close()

    second_service, second_memory = build_test_service(
        database_path=database_path,
    )

    result = second_service.invoke(
        user_input="我的编号是什么？",
        thread_id=thread_id,
        context=context,
    )

    assert "RESTART-2026" in result["answer"]

    second_memory.close()
