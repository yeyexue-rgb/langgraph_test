"""空工具提供者，用于框架初始化阶段。"""

from __future__ import annotations

from typing import Any


class EmptyToolProvider:
    """基础框架默认的空工具提供者。"""

    @property
    def name(self) -> str:
        return "core"

    def get_tools(self) -> list[Any]:
        return []

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "tool_count": 0,
            "message": "当前未注册业务工具",
        }
