from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

from agent_core.agent_service import AgentService
from agent_core.context import AgentContext
from agent_core.registry import ToolRegistry
from agent_core.settings import load_agent_settings
from agent_core.sqlite_memory import (
    SQLiteMemory,
    create_sqlite_memory,
)
from providers.empty_provider import EmptyToolProvider
from providers.file_provider import FileToolProvider
from providers.time_provider import TimeToolProvider

load_dotenv()


DATABASE_PATH = Path("data/agent_memory.sqlite3")


# ============================================================================
# 1. Streamlit Session State & thread_id 持久化
# ============================================================================

def get_or_create_thread_id() -> str:
    """从 URL query param 读取 thread_id，不存在则生成并写回 URL。

    Streamlit 重启后 Session State 被清空，但 URL 参数仍然存在，
    因此把 thread_id 放在 URL 是重启后恢复会话的关键。
    """

    query_thread_id = st.query_params.get("thread_id")

    if query_thread_id:
        thread_id = str(query_thread_id).strip()
    else:
        thread_id = str(uuid.uuid4())
        st.query_params["thread_id"] = thread_id

    return thread_id


def initialize_session() -> None:
    defaults: dict[str, Any] = {
        # thread_id 由 get_or_create_thread_id 从 URL 决定，
        # 不在这里随机生成，避免重启后丢失原会话。
        "messages": [],
        "traces": [],
        "agent_service": None,
        "sqlite_memory": None,
        "loaded_thread_id": None,
        "service_error": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = (
            get_or_create_thread_id()
        )


def create_new_thread() -> None:
    """新建会话：生成新 thread_id 并同步到浏览器地址栏。"""

    new_thread_id = str(uuid.uuid4())

    st.session_state.thread_id = new_thread_id
    st.session_state.messages = []
    st.session_state.traces = []
    st.session_state.loaded_thread_id = None
    st.session_state.service_error = None

    # 同步更新浏览器地址，保证刷新/重启后仍能定位到新会话。
    st.query_params["thread_id"] = new_thread_id


# ============================================================================
# 2. Agent 初始化（SQLite 持久化短期记忆）
# ============================================================================

@st.cache_resource
def build_agent_service() -> tuple[
    AgentService,
    SQLiteMemory,
]:
    """构建 Agent 并返回 (service, memory)。

    使用 @st.cache_resource 保证 Agent 与 SQLite 连接被长期复用，
    不会在每次请求时重建。返回 memory 是为了让连接生命周期与
    缓存资源保持一致，避免连接被提前释放导致状态读写失败。
    """

    settings = load_agent_settings()

    registry = ToolRegistry()
    registry.register(EmptyToolProvider())
    registry.register(TimeToolProvider())
    registry.register(FileToolProvider())

    memory = create_sqlite_memory(DATABASE_PATH)

    service = AgentService(
        settings=settings,
        tool_registry=registry,
        checkpointer=memory.checkpointer,
    )

    return service, memory


def get_agent_service() -> AgentService | None:
    if st.session_state.agent_service is not None:
        return st.session_state.agent_service

    try:
        service, memory = build_agent_service()

        st.session_state.agent_service = service
        st.session_state.sqlite_memory = memory
        st.session_state.service_error = None

        return service

    except Exception as exc:
        st.session_state.service_error = str(exc)
        return None


def load_ui_messages(
    service: AgentService,
    thread_id: str,
) -> list[dict[str, str]]:
    """从 Agent State 读取消息，恢复页面聊天内容。"""

    messages = service.get_thread_messages(thread_id)
    result: list[dict[str, str]] = []

    for message in messages:
        if isinstance(message, HumanMessage):
            result.append(
                {
                    "role": "user",
                    "content": str(message.content),
                }
            )

        elif (
            isinstance(message, AIMessage)
            and not getattr(message, "tool_calls", [])
            and message.content
        ):
            result.append(
                {
                    "role": "assistant",
                    "content": str(message.content),
                }
            )

    return result


# ============================================================================
# 3. 页面样式
# ============================================================================

st.set_page_config(
    page_title="测试 Agent 平台",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .block-container {
            max-width: 1440px;
            padding-top: 1.2rem;
            padding-bottom: 1.5rem;
        }

        h1 {
            font-size: 1.8rem !important;
            margin-bottom: 0.15rem !important;
        }

        h2, h3 {
            margin-top: 0.6rem !important;
            margin-bottom: 0.45rem !important;
        }

        div[data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }

        div[data-testid="stMetric"] {
            padding: 0.45rem 0.65rem;
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 0.5rem;
        }

        div[data-testid="stMetricValue"] {
            font-size: 1.25rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================================
# 4. 页面初始化
# ============================================================================

initialize_session()

service = get_agent_service()
settings = load_agent_settings()

# ============================================================================
# 4.1 启动时根据 thread_id 自动恢复页面消息
# ============================================================================
#
# SQLite 保存会话内容，thread_id 是找到会话的钥匙，
# URL 参数负责在 Streamlit 重启后保留这把钥匙。
# 当 thread_id 变化（新建会话或从 URL 恢复）时，
# 自动从 Agent State 加载历史 UI 消息。

current_thread_id: str = st.session_state.thread_id

if (
    st.session_state.get("loaded_thread_id")
    != current_thread_id
):
    if service is not None:
        st.session_state.messages = load_ui_messages(
            service,
            current_thread_id,
        )
    else:
        st.session_state.messages = []

    st.session_state.loaded_thread_id = current_thread_id

with st.sidebar:
    st.header("运行配置")

    user_id = st.text_input(
        "用户 ID",
        value="tester-001",
    )

    tenant_id = st.text_input(
        "租户 / 团队",
        value="qa-team",
    )

    roles = st.multiselect(
        "角色",
        options=[
            "tester",
            "qa_lead",
            "developer",
            "admin",
        ],
        default=["tester"],
    )

    st.divider()

    st.caption("模型")
    st.code(settings.model_name)

    st.caption("工具提供者")
    if service is not None:
        providers = service.tool_registry.list_providers()
        st.write(providers)
    else:
        st.write("Agent 尚未初始化")

    st.divider()

    st.subheader("会话管理")
    st.caption("当前会话 thread_id")
    st.code(st.session_state.thread_id)

    memory: SQLiteMemory | None = st.session_state.sqlite_memory
    if memory is not None:
        st.caption(f"记忆数据库：{memory.database_path}")

    if st.button("新建会话", use_container_width=True):
        create_new_thread()
        st.rerun()

    if st.button("重新初始化 Agent", use_container_width=True):
        st.session_state.agent_service = None
        st.session_state.sqlite_memory = None
        st.session_state.service_error = None
        st.rerun()


header_left, header_right = st.columns([5, 1])

with header_left:
    st.title("🧪 测试 Agent 平台")
    st.caption(
        "基础框架：会话管理、Runtime Context、工具注册、调用追踪、SQLite 短期记忆"
    )

with header_right:
    st.metric(
        "已注册工具",
        len(service.tool_registry.get_tools()) if service else 0,
    )


if st.session_state.service_error:
    st.error(
        f"Agent 初始化失败：{st.session_state.service_error}"
    )
    st.info(
        "请检查 DASHSCOPE_API_KEY、模型名称和依赖版本。"
    )


if service is not None:
    context = AgentContext(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=tuple(roles),
        approved_actions=(),
        metadata={
            "source": "streamlit",
        },
    )

    st.divider()
    st.subheader("对话区")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_input = st.chat_input(
        "输入测试相关问题，例如：请介绍当前平台能力"
    )

    if user_input:
        st.session_state.messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Agent 正在思考……"):
                try:
                    result = service.invoke(
                        user_input=user_input,
                        thread_id=st.session_state.thread_id,
                        context=context,
                    )

                    answer = result["answer"]

                    if not answer:
                        answer = (
                            "Agent 没有返回文本结果，请查看调用轨迹。"
                        )

                    st.markdown(answer)

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": answer,
                        }
                    )

                    st.session_state.traces.extend(
                        result["traces"]
                    )

                except Exception as exc:
                    error_message = f"Agent 执行异常：{exc}"
                    st.error(error_message)

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": error_message,
                        }
                    )

    st.divider()

    trace_tab, health_tab, config_tab = st.tabs(
        [
            "调用轨迹",
            "平台状态",
            "运行配置",
        ]
    )

    with trace_tab:
        if st.session_state.traces:
            st.dataframe(
                st.session_state.traces,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("当前会话还没有工具调用或模型运行轨迹。")

    with health_tab:
        st.write(
            service.tool_registry.health_check()
        )

    with config_tab:
        st.json(
            {
                "thread_id": st.session_state.thread_id,
                "model": settings.model_name,
                "base_url": settings.base_url,
                "user_id": context.user_id,
                "tenant_id": context.tenant_id,
                "roles": context.roles,
                "tool_providers": (
                    service.tool_registry.list_providers()
                ),
                "tool_count": len(
                    service.tool_registry.get_tools()
                ),
                "checkpointer": "SqliteSaver",
                "database_path": str(DATABASE_PATH),
            }
        )
