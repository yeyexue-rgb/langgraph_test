from __future__ import annotations

import uuid
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from agent_core.agent_service import AgentService
from agent_core.context import AgentContext
from agent_core.registry import ToolRegistry
from agent_core.settings import load_agent_settings
from providers.empty_provider import EmptyToolProvider
from providers.file_provider import FileToolProvider
from providers.time_provider import TimeToolProvider

load_dotenv()


# ============================================================================
# 1. Streamlit Session State
# ============================================================================

def initialize_session() -> None:
    defaults: dict[str, Any] = {
        "thread_id": str(uuid.uuid4()),
        "messages": [],
        "traces": [],
        "agent_service": None,
        "service_error": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_session() -> None:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.traces = []
    st.session_state.service_error = None


# ============================================================================
# 2. Agent 初始化
# ============================================================================

def get_agent_service() -> AgentService | None:
    if st.session_state.agent_service is not None:
        return st.session_state.agent_service

    try:
        settings = load_agent_settings()

        registry = ToolRegistry()

        registry.register(EmptyToolProvider())
        registry.register(TimeToolProvider())
        registry.register(FileToolProvider())

        service = AgentService(
            settings=settings,
            tool_registry=registry,
        )

        st.session_state.agent_service = service
        st.session_state.service_error = None

        return service

    except Exception as exc:
        st.session_state.service_error = str(exc)
        return None


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

    if st.button("新建会话", use_container_width=True):
        clear_session()
        st.rerun()

    if st.button("重新初始化 Agent", use_container_width=True):
        st.session_state.agent_service = None
        st.session_state.service_error = None
        st.rerun()


header_left, header_right = st.columns([5, 1])

with header_left:
    st.title("🧪 测试 Agent 平台")
    st.caption(
        "基础框架：会话管理、Runtime Context、工具注册、调用追踪"
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
            }
        )
