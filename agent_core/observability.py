"""Langfuse 轨迹追踪接入（Agent 可观测性）。

定位：**评测（DeepEval）判质量，追踪（Langfuse）看过程**。
评测回答"这次过没过"，追踪回答"过程里到底发生了什么、慢在哪、错在哪一步"。

设计原则（三条，都是为了不破坏既有回归基线）：
1. **可选、零侵入**：未配置 LANGFUSE_* 时自动降级为 no-op，
   `build_langfuse_handler()` 返回 None，运行配置原样返回，
   Agent 行为与不加追踪时**完全一致**；
2. **可开关、可采样**：`LANGFUSE_ENABLED` 显式开关；
   `LANGFUSE_SAMPLE_RATE` 支持按比例采样（控制成本与数据量）；
3. **默认脱敏**：`LANGFUSE_MASK=1`（默认开）对 API Key、
   绝对路径等敏感形态做递归掩码，避免把密钥写进追踪平台。

环境变量：
    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY   必填（缺一即视为未启用）
    LANGFUSE_HOST            默认官方云，自托管时指向自己的地址
    LANGFUSE_ENABLED         1/0，显式开关（默认：配了 key 即启用）
    LANGFUSE_SAMPLE_RATE     0~1，采样比例（默认 1.0 全量）
    LANGFUSE_MASK            1/0，脱敏开关（默认 1）
    LANGFUSE_ENVIRONMENT     环境名（如 local / staging / prod）
    LANGFUSE_RELEASE         版本号（如 git sha），便于按版本对比
"""

from __future__ import annotations

import logging
import os
import random
import re
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "langfuse_enabled",
    "sample_rate",
    "should_trace",
    "build_langfuse_handler",
    "trace_config",
    "flush",
    "reset",
]

_client: Any = None
_handler: Any = None
_warned = False

# ---------------------------------------------------------------- 环境变量


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _flag(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()

    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False

    return default


def langfuse_enabled() -> bool:
    """是否启用 Langfuse 追踪：显式开关优先，其次看是否配了密钥。"""

    has_keys = bool(_env("LANGFUSE_PUBLIC_KEY") and _env("LANGFUSE_SECRET_KEY"))
    explicit = _env("LANGFUSE_ENABLED")

    if explicit:
        return _flag("LANGFUSE_ENABLED") and has_keys

    return has_keys


def sample_rate() -> float:
    """采样比例（0~1），用于控制追踪数据量与平台成本。"""

    try:
        return max(0.0, min(1.0, float(_env("LANGFUSE_SAMPLE_RATE", "1.0"))))
    except ValueError:
        return 1.0


def should_trace() -> bool:
    """本次调用是否要追踪（未启用或未命中采样时为 False）。"""

    if not langfuse_enabled():
        return False

    rate = sample_rate()

    return True if rate >= 1.0 else random.random() < rate


# ---------------------------------------------------------------- 脱敏

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),                      # OpenAI/百炼风格 key
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*\S+"),
)
_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\[^\s\"']+"),                        # Windows 绝对路径
    re.compile(r"/(?:home|Users|root|tmp)/[^\s\"']+"),          # Unix 绝对路径
)


def _mask_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    for pattern in _PATH_PATTERNS:
        text = pattern.sub("[PATH]", text)

    return text


def _mask(data: Any) -> Any:
    """递归脱敏：字符串按规则替换，容器逐层下钻。"""

    if _env("LANGFUSE_MASK", "1").lower() in ("0", "false", "no", "off"):
        return data

    if isinstance(data, str):
        return _mask_text(data)
    if isinstance(data, dict):
        return {k: _mask(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_mask(v) for v in data]

    return data


# ---------------------------------------------------------------- 客户端与回调


def _init_client() -> Any:
    """初始化（并缓存）Langfuse 客户端；失败时返回 None 并只告警一次。"""

    global _client, _warned

    if _client is not None:
        return _client

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=_env("LANGFUSE_PUBLIC_KEY"),
            secret_key=_env("LANGFUSE_SECRET_KEY"),
            host=_env("LANGFUSE_HOST") or None,
            environment=_env("LANGFUSE_ENVIRONMENT") or None,
            release=_env("LANGFUSE_RELEASE") or None,
            mask=_mask,
        )

        return _client
    except Exception as exc:  # noqa: BLE001 —— 追踪失败绝不能影响业务
        if not _warned:
            logger.warning("Langfuse 初始化失败，已降级为不追踪：%s", exc)
            _warned = True

        return None


def build_langfuse_handler() -> Any | None:
    """构造 LangChain 回调处理器；未启用/初始化失败时返回 None。"""

    global _handler, _warned

    if not langfuse_enabled():
        return None

    if _handler is not None:
        return _handler

    _init_client()

    try:
        from langfuse.langchain import CallbackHandler

        _handler = CallbackHandler()

        return _handler
    except Exception as exc:  # noqa: BLE001
        if not _warned:
            logger.warning("Langfuse 回调处理器创建失败，已降级：%s", exc)
            _warned = True

        return None


def trace_config(
    *,
    thread_id: str,
    user_id: str | None = None,
    tenant_id: str | None = None,
    agent_mode: str | None = None,
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
    """构造要合并进 LangGraph 运行配置的追踪字段。

    - callbacks：Langfuse 回调处理器；
    - metadata：把会话/用户/租户映射成 Langfuse 的 session / user / tags，
      这样在平台里能按"一次会话"回放完整链路；
    - run_name / tags：便于筛选与聚合。
    """

    handler = build_langfuse_handler()

    if handler is None:
        return {}

    tags = ["agent", f"mode:{agent_mode or 'unknown'}"]
    if tenant_id:
        tags.append(f"tenant:{tenant_id}")
    if extra_tags:
        tags.extend(extra_tags)

    return {
        "callbacks": [handler],
        "run_name": f"agent-{agent_mode or 'unknown'}",
        "tags": tags,
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_user_id": user_id or "anonymous",
            "langfuse_tags": tags,
            "agent_mode": agent_mode,
            "tenant_id": tenant_id,
        },
    }


def flush() -> None:
    """把缓冲区里的追踪数据推到 Langfuse。

    进程即将退出（脚本、定时任务、测试收尾）时调用；
    Web 常驻服务不需要每次调用都 flush。
    """

    if _client is None:
        return

    try:
        _client.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse flush 失败：%s", exc)


def reset() -> None:
    """清空缓存的客户端/处理器（测试用）。"""

    global _client, _handler, _warned
    _client, _handler, _warned = None, None, False
