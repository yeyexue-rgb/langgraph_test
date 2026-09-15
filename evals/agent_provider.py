"""promptfoo Python Provider —— 黑盒接法"方式 2"的项目落地。

把本项目 AgentService 包装成 promptfoo 可调用的 Provider：
同一套用例分别打在 single / subagents 两种架构上，输出 A/B 对比报告。

运行（项目根目录，需要 Node.js，先激活项目 venv）：
    npx promptfoo@latest eval evals/promptfooconfig.yaml
    npx promptfoo@latest view

设计要点：
- 被测对象与 Streamlit 页面完全同源（同一个 AgentService 构建逻辑，
  见 _build_service 与 app.py 的对齐关系），评测结论可直接代表页面行为；
- 每个用例独立 thread_id，避免 checkpointer 记忆污染用例间结果；
- 评测记忆默认走 AgentService 内置的 InMemorySaver，
  不写页面的会话库 data/agent_memory.sqlite3；
- 文件场景的个人空间自动准备在 data/eval_personal_space，
  跨机器可复现，不依赖本机 D:\\个人空间 是否存在。
"""

from __future__ import annotations

import dataclasses
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

# promptfoo 的 Python Provider 进程不一定从项目根目录启动，
# 保险起见把项目根加入 sys.path，保证 agent_core / providers 可导入。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_core.agent_service import AgentService  # noqa: E402
from agent_core.context import AgentContext  # noqa: E402
from agent_core.hitl import build_hitl_middleware  # noqa: E402
from agent_core.registry import ToolRegistry  # noqa: E402
from agent_core.settings import load_agent_settings  # noqa: E402
from providers.empty_provider import EmptyToolProvider  # noqa: E402
from providers.file_provider import FileToolProvider  # noqa: E402
from providers.sql_provider import SQLAgentProvider  # noqa: E402
from providers.time_provider import TimeToolProvider  # noqa: E402

EVAL_SQL_DATABASE = PROJECT_ROOT / "data" / "test_management.db"
EVAL_PERSONAL_SPACE = PROJECT_ROOT / "data" / "eval_personal_space"

# Agent 构建开销大（模型客户端 + 全量工具），按模式缓存单例复用。
_SERVICE_CACHE: dict[str, AgentService] = {}
_SERVICE_LOCK = threading.Lock()


def _seed_eval_personal_space(directory: Path) -> None:
    """准备文件场景的评测个人空间（幂等，只写一次）。"""

    directory.mkdir(parents=True, exist_ok=True)

    pdf = directory / "回归报告.pdf"
    if not pdf.exists():
        pdf.write_bytes(b"%PDF-eval-seed")

    script = directory / "test_login.py"
    if not script.exists():
        script.write_text(
            "def test_login(): pass\n",
            encoding="utf-8",
        )


def _build_service(agent_mode: str) -> AgentService:
    """按架构模式构建 AgentService（构建逻辑与 app.py 的页面保持同源）。"""

    if agent_mode not in ("single", "subagents"):
        raise ValueError(
            f"agent_mode 必须是 ('single', 'subagents') 之一：{agent_mode!r}"
        )

    base_settings = load_agent_settings()

    if not base_settings.api_key:
        raise ValueError("未配置 DASHSCOPE_API_KEY，请在 .env 中配置。")

    if not EVAL_SQL_DATABASE.exists():
        raise FileNotFoundError(
            f"SQL 业务库不存在：{EVAL_SQL_DATABASE}，"
            "请先运行 python scripts/seed_test_db.py 生成种子数据。"
        )

    _seed_eval_personal_space(EVAL_PERSONAL_SPACE)

    settings = dataclasses.replace(base_settings, agent_mode=agent_mode)

    # SQL Agent 的查询双重检查需要独立的 model 实例（与 app.py 一致）。
    sql_model = ChatOpenAI(
        model=base_settings.model_name,
        api_key=base_settings.api_key,
        base_url=base_settings.base_url,
        temperature=0,
        streaming=False,
        extra_body={"enable_thinking": False},
    )

    registry = ToolRegistry()
    registry.register(EmptyToolProvider())
    registry.register(TimeToolProvider())
    registry.register(FileToolProvider(root_directory=EVAL_PERSONAL_SPACE))
    registry.register(
        SQLAgentProvider(
            database_path=EVAL_SQL_DATABASE,
            model=sql_model,
        )
    )

    # single 模式挂 HITL 审批中间件；subagents 模式由子 Agent 内部自建。
    middleware = [build_hitl_middleware()] if agent_mode == "single" else []

    return AgentService(
        settings=settings,
        tool_registry=registry,
        middleware=middleware,
    )


def _get_service(agent_mode: str) -> AgentService:
    """获取（或构建并缓存）指定架构的 AgentService 单例。"""

    with _SERVICE_LOCK:
        service = _SERVICE_CACHE.get(agent_mode)

        if service is None:
            service = _build_service(agent_mode)
            _SERVICE_CACHE[agent_mode] = service

        return service


def invoke_agent(
    query: str,
    agent_mode: str = "single",
) -> dict[str, Any]:
    """评测统一入口：以独立 thread_id 调用 AgentService，返回归一化结果。

    promptfoo（本文件 call_api）与 DeepEval（evals/test_agent_eval.py）
    共用这一条调用通道——两个工具打的被测对象、调用方式与页面完全一致。

    每个用例独立 thread_id 是关键：checkpointer 按 thread_id 恢复历史，
    共用会导致第二条用例带上第一条的上下文（评测结果被记忆污染）。
    """

    service = _get_service(agent_mode)

    context = AgentContext(
        user_id="eval-runner",
        tenant_id="qa-team",
        roles=("tester",),
        metadata={"source": "eval"},
    )

    return service.invoke(
        user_input=query,
        thread_id=f"eval-{uuid.uuid4()}",
        context=context,
    )


def call_api(
    prompt: str,
    options: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """promptfoo Python Provider 入口。

    provider 配置里的 config.agent_mode 决定打在哪个架构上：

        providers:
          - id: 'file://evals/agent_provider.py'
            config: { agent_mode: single }
    """

    config = (options or {}).get("config") or {}
    agent_mode = str(config.get("agent_mode") or "single")

    try:
        result = invoke_agent(prompt, agent_mode=agent_mode)
    except Exception as exc:  # noqa: BLE001 —— 交给 promptfoo 标记为用例错误
        return {"output": "", "error": f"Agent 调用失败：{exc}"}

    if result.get("status") == "interrupted":
        # HITL 中断：没有最终回答，把"被拦截"这一事实写进 output，
        # 供 contains / not-contains 断言（安全用例的期望行为）。
        pending_tools = ", ".join(
            action.get("name", "")
            for action in result.get("pending_actions", [])
        )
        return {"output": f"[HITL 审批拦截] 待审批工具：{pending_tools}"}

    return {"output": str(result.get("answer") or "")}
