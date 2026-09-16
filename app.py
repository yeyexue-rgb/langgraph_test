from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from agent_core.agent_service import AgentService
from agent_core.context import AgentContext
from agent_core.hitl import build_hitl_middleware
from agent_core.registry import ToolRegistry
from agent_core.settings import load_agent_settings
from agent_core.sqlite_memory import (
    SQLiteMemory,
    create_sqlite_memory,
)
from agent_core.structured_output import AgentResponse
from providers.empty_provider import EmptyToolProvider
from providers.file_provider import FileToolProvider
from providers.sql_provider import (
    DEFAULT_DATABASE_PATH as SQL_DATABASE_PATH,
    SQLAgentProvider,
)
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
        "structured_response": None,
        "tools_used": [],
        "agent_service": None,
        "sqlite_memory": None,
        "loaded_thread_id": None,
        "pending_interrupt": None,
        "agent_mode": "single",
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
    # 这两个字段表示“最近一轮”的结果，不应该被带入新会话。
    st.session_state.structured_response = None
    st.session_state.tools_used = []
    st.session_state.loaded_thread_id = None
    st.session_state.pending_interrupt = None
    st.session_state.service_error = None

    # 同步更新浏览器地址，保证刷新/重启后仍能定位到新会话。
    st.query_params["thread_id"] = new_thread_id


# ============================================================================
# 2. Agent 初始化（SQLite 持久化短期记忆）
# ============================================================================

@st.cache_resource
def build_agent_service(
    agent_mode: str,
) -> tuple[AgentService, SQLiteMemory]:
    """构建 Agent 并返回 (service, memory)。

    agent_mode 是灰度开关（按模式分别缓存）：
    - single：单 Agent 基线，直接持有业务工具；
    - subagents：Supervisor + 领域子 Agent（内部自建 HITL）。

    使用 @st.cache_resource 保证 Agent 与 SQLite 连接被长期复用，
    不会在每次请求时重建。返回 memory 是为了让连接生命周期与
    缓存资源保持一致，避免连接被提前释放导致状态读写失败。
    """

    settings = dataclasses.replace(
        load_agent_settings(),
        agent_mode=agent_mode,
    )

    registry = ToolRegistry()
    registry.register(EmptyToolProvider())
    registry.register(TimeToolProvider())
    registry.register(FileToolProvider())

    # SQL Agent 需要 model 做查询双重检查；
    # single 模式复用同一个 model，subagents 模式也复用。
    settings_for_sql = load_agent_settings()
    sql_model = ChatOpenAI(
        model=settings_for_sql.model_name,
        api_key=settings_for_sql.api_key,
        base_url=settings_for_sql.base_url,
        temperature=0,
        streaming=False,
        extra_body={"enable_thinking": False},
    )
    registry.register(
        SQLAgentProvider(
            database_path=SQL_DATABASE_PATH,
            model=sql_model,
        )
    )

    memory = create_sqlite_memory(DATABASE_PATH)

    # subagents 模式下 Supervisor 内部自建针对 file_specialist
    # 的 HITL 审批中间件，无需外部注入。
    middleware = (
        [build_hitl_middleware()]
        if agent_mode == "single"
        else []
    )

    service = AgentService(
        settings=settings,
        tool_registry=registry,
        checkpointer=memory.checkpointer,
        middleware=middleware,
    )

    return service, memory


def get_agent_service() -> AgentService | None:
    if st.session_state.agent_service is not None:
        return st.session_state.agent_service

    try:
        service, memory = build_agent_service(
            st.session_state.get("agent_mode", "single"),
        )

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
    """从持久化消息中恢复页面聊天记录。

    使用 ToolStrategy 后，最终答案可能保存在 AgentResponse 工具调用的
    参数中，而不是普通 AIMessage.content。因此需要同时兼容：
    1. 普通文本回答；
    2. AgentResponse 结构化工具调用。
    """

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
            continue

        if not isinstance(message, AIMessage):
            continue

        tool_calls = getattr(message, "tool_calls", [])

        # 普通文本回答
        if not tool_calls and message.content:
            result.append(
                {
                    "role": "assistant",
                    "content": str(message.content),
                }
            )
            continue

        # 从 AgentResponse 结构化工具调用中提取 answer
        for tool_call in tool_calls:
            if tool_call.get("name") != AgentResponse.__name__:
                continue

            arguments = tool_call.get("args", {})
            answer = arguments.get("answer")

            if not answer:
                continue

            result.append(
                {
                    "role": "assistant",
                    "content": str(answer),
                }
            )

    return result


def process_agent_result(result: dict[str, Any]) -> None:
    """统一处理 Agent 结果：最终回答或新的待审批操作。

    - status == "interrupted"：HITL 中间件拦截了危险工具调用，
      记录 pending_interrupt，等待用户批准/拒绝；
    - 其他：正常最终回答。
    """

    if result.get("status") == "interrupted":
        actions = result.get("pending_actions", [])

        st.session_state.pending_interrupt = {
            "thread_id": st.session_state.thread_id,
            "actions": actions,
        }

        summary_lines = ["⏸️ 以下操作需要人工审批："]

        for action in actions:
            summary_lines.append(f"- **{action['name']}**")

        summary_lines.append("请在下方选择处理方式。")

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "\n".join(summary_lines),
            }
        )

        return

    answer = result.get("answer") or (
        "Agent 没有返回文本结果，请查看调用轨迹。"
    )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )

    st.session_state.traces.extend(result.get("traces", []))
    st.session_state.structured_response = result.get(
        "structured_response",
    )
    st.session_state.tools_used = result.get("tools_used", [])


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

    # ========================================================================
    # 架构模式切换（灰度开关）：切换时重建 Agent 并新建会话，
    # 避免单 Agent 与 Supervisor 共用同一 thread 的状态结构冲突。
    # ========================================================================

    current_mode = st.session_state.get("agent_mode", "single")

    agent_mode_label = st.selectbox(
        "Agent 架构模式",
        options=["single", "subagents"],
        index=["single", "subagents"].index(current_mode),
        format_func={
            "single": "单 Agent（基线）",
            "subagents": "Multi-Agent（Supervisor + 子 Agent）",
        }.get,
    )

    if agent_mode_label != current_mode:
        st.session_state.agent_mode = agent_mode_label
        st.session_state.agent_service = None
        st.session_state.sqlite_memory = None
        st.session_state.service_error = None
        # 架构切换 = 新会话：不同架构的图状态结构不同，
        # 共用 thread_id 会导致 checkpoint 恢复异常。
        create_new_thread()
        st.rerun()

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

    # ========================================================================
    # HITL 审批区：存在待审批操作时展示，并阻断新输入
    # ========================================================================

    pending = st.session_state.get("pending_interrupt")

    # 丢弃属于其他线程的待审批请求（例如已新建会话）。
    if pending and pending["thread_id"] != st.session_state.thread_id:
        st.session_state.pending_interrupt = None
        pending = None

    if pending:
        st.warning("以下工具调用等待人工审批：")

        for action in pending["actions"]:
            st.json(
                {
                    "tool": action["name"],
                    "args": action["args"],
                    "allowed_decisions": action.get(
                        "allowed_decisions",
                        [],
                    ),
                }
            )

        reject_message = st.text_input(
            "拒绝原因（可选）",
            key="hitl_reject_message",
        )

        approve_col, reject_col = st.columns(2)

        with approve_col:
            if st.button(
                "✅ 批准执行",
                use_container_width=True,
                type="primary",
            ):
                decisions = [
                    {"type": "approve"}
                    for _ in pending["actions"]
                ]

                with st.spinner("Agent 正在继续执行……"):
                    try:
                        result = service.resume(
                            thread_id=pending["thread_id"],
                            decisions=decisions,
                            context=context,
                        )

                        st.session_state.pending_interrupt = None
                        process_agent_result(result)

                    except Exception as exc:
                        st.session_state.pending_interrupt = None
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": f"审批恢复异常：{exc}",
                            }
                        )

                st.rerun()

        with reject_col:
            if st.button(
                "❌ 拒绝执行",
                use_container_width=True,
            ):
                message = (
                    reject_message.strip()
                    or "人工审核拒绝该操作"
                )

                decisions = [
                    {"type": "reject", "message": message}
                    for _ in pending["actions"]
                ]

                with st.spinner("Agent 正在处理拒绝反馈……"):
                    try:
                        result = service.resume(
                            thread_id=pending["thread_id"],
                            decisions=decisions,
                            context=context,
                        )

                        st.session_state.pending_interrupt = None
                        process_agent_result(result)

                    except Exception as exc:
                        st.session_state.pending_interrupt = None
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": f"审批恢复异常：{exc}",
                            }
                        )

                st.rerun()

    user_input = st.chat_input(
        "输入测试相关问题，例如：请介绍当前平台能力"
        if not pending
        else "存在待审批操作，请先处理上方审批"
    )

    if user_input:
        if pending:
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "⚠️ 存在待审批操作，"
                        "请先点击批准或拒绝后再继续对话。"
                    ),
                }
            )
            st.rerun()

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

                    process_agent_result(result)

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

    trace_tab, result_tab, health_tab, config_tab = st.tabs(
        [
            "调用轨迹",
            "结构化结果",
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

    with result_tab:
        structured = st.session_state.structured_response

        if structured is None:
            st.info("当前会话还没有结构化结果。")
        else:
            status = structured["status"]

            if status == "success":
                st.success("本轮任务执行成功")
            elif status == "partial_success":
                st.warning("本轮任务仅部分完成")
            elif status == "needs_clarification":
                st.info("需要用户补充信息")
            else:
                st.error("本轮任务执行失败")

            if structured.get("needs_human_review", False):
                st.warning("当前结果需要人工复核")

            error_code = structured.get("error_code")

            if error_code:
                st.code(error_code, language="text")

            st.write("最终回答")
            st.write(structured["answer"])

            st.write("实际调用的业务工具")
            st.json(st.session_state.tools_used)

            st.write("完整结构化响应")
            st.json(structured)

    with health_tab:
        st.write(
            service.tool_registry.health_check()
        )

    with config_tab:
        st.json(
            {
                "thread_id": st.session_state.thread_id,
                "agent_mode": st.session_state.get(
                    "agent_mode",
                    "single",
                ),
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
