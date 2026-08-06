"""平台运行时上下文定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    """Agent 每次运行时携带的业务上下文。

    这些字段由服务端注入，不允许模型通过普通工具参数传入，
    避免模型伪造 user_id、tenant_id、角色或审批结果。
    """

    user_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    approved_actions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
