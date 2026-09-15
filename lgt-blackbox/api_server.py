"""黑盒评测适配器：把 langgraph_test 的 AgentService 暴露为 HTTP 接口。

设计原则（黑盒）：
- 评测代码只通过 HTTP 与系统交互（POST /chat），不 import 项目内部模块；
- 本文件是"接口层"，负责把 HTTP 请求翻译成 AgentService.invoke 调用；
- 支持 LGT_MOCK=1（无模型可用时返回固定响应，用于端到端演示与 CI 自测）。

端点：
  GET  /health          健康检查（模式、工具清单、依赖健康）
  POST /chat            会话请求 {message, thread_id?, user_id?, tenant_id?}
  POST /_admin/new_thread  生成并返回一个 thread_id

运行：
  uvicorn api_server:app --host 127.0.0.1 --port 8088
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

REPO = Path(os.getenv("LGT_REPO", str(Path(__file__).resolve().parent.parent / "langgraph_test"))).resolve()
sys.path.insert(0, str(REPO))
load_dotenv(REPO / ".env")

MOCK = os.getenv("LGT_MOCK", "0") == "1"

app = FastAPI(title="langgraph_test 黑盒评测接口", version="0.1.0")

_state: dict = {"service": None, "registry": None, "error": None}


def _build_service():
    from agent_core.agent_service import AgentService
    from agent_core.registry import ToolRegistry
    from agent_core.settings import load_agent_settings
    from providers.empty_provider import EmptyToolProvider
    from providers.time_provider import TimeToolProvider

    registry = ToolRegistry()
    registry.register(EmptyToolProvider())
    registry.register(TimeToolProvider())

    # 文件检索工具（可选）：若配置了沙箱目录则注册
    sandbox = os.getenv("LGT_FILE_ROOT", "")
    if sandbox and Path(sandbox).exists():
        from providers.file_provider import FileToolProvider
        registry.register(FileToolProvider(root_directory=sandbox))

    settings = load_agent_settings()
    return AgentService(settings=settings, tool_registry=registry), registry


@app.on_event("startup")
def _startup() -> None:
    if MOCK:
        _state["service"] = None
        _state["error"] = "MOCK 模式"
        return
    try:
        service, registry = _build_service()
        _state["service"], _state["registry"] = service, registry
    except Exception as exc:  # noqa: BLE001
        _state["error"] = f"{type(exc).__name__}: {exc}"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = None
    user_id: str = "tester"
    tenant_id: str = "qa-team"


MOCK_RULES = [
    ("明天下午3点", "“明天下午3点”对应标准时间为次日 15:00（Asia/Shanghai）。工具解析结果：parse_natural_datetime → 成功。"),
    ("现在", "当前系统时间为 2026-09-15 23:33（Asia/Shanghai），对应 ISO 8601：2026-09-15T23:33:00+08:00。"),
    ("加", "按日期加法计算：2026-09-15 + 10 天 = 2026-09-25。"),
    ("差", "两个日期的差值为 14 天。"),
    ("某个时候", "抱歉，我无法解析“某个时候”这类模糊表达，请提供更具体的时间（例如“明天下午 3 点”）。"),
    ("删", "抱歉，我不能执行删除数据或越权操作。如需数据变更，请走变更审批流程。"),
]


def _mock_answer(message: str) -> str:
    for key, answer in MOCK_RULES:
        if key in message:
            return answer
    return "好的，我已经理解你的问题，正在按你的要求给出简洁的回答。"


@app.get("/health")
def health() -> dict:
    if MOCK:
        return {"status": "ok", "mock": True, "error": None}
    registry = _state.get("registry")
    tools = [t.name for t in registry.get_tools()] if registry else []
    return {
        "status": "ok" if _state.get("service") else "degraded",
        "mock": False,
        "tools": tools,
        "providers": registry.list_providers() if registry else [],
        "health": registry.health_check() if registry else {},
        "error": _state.get("error"),
    }


@app.post("/_admin/new_thread")
def new_thread() -> dict:
    return {"thread_id": str(uuid.uuid4())}


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    thread_id = req.thread_id or str(uuid.uuid4())
    started = time.time()

    if MOCK:
        answer = _mock_answer(req.message)
        return {
            "status": "success" if "抱歉" not in answer else "refused",
            "answer": answer,
            "tools_used": [],
            "traces": [],
            "thread_id": thread_id,
            "latency_ms": int((time.time() - started) * 1000),
            "mock": True,
        }

    service = _state.get("service")
    if service is None:
        raise HTTPException(status_code=503, detail=f"服务未就绪：{_state.get('error')}")

    try:
        from agent_core.context import AgentContext

        result = service.invoke(
            user_input=req.message,
            thread_id=thread_id,
            context=AgentContext(user_id=req.user_id, tenant_id=req.tenant_id, roles=("tester",)),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Agent 调用失败：{type(exc).__name__}: {exc}") from exc

    return {
        "status": result.get("status"),
        "answer": result.get("answer", ""),
        "tools_used": result.get("tools_used", []),
        "traces": result.get("traces", []),
        "thread_id": thread_id,
        "latency_ms": int((time.time() - started) * 1000),
        "mock": False,
    }
