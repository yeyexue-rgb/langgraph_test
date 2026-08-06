"""工具提供者协议与统一注册中心。"""

from __future__ import annotations

from typing import Any, Protocol


class ToolProvider(Protocol):
    """工具提供者协议。

    新增工具时，只需要实现该协议并注册到 ToolRegistry，
    不需要修改页面代码或 AgentService。
    """

    @property
    def name(self) -> str:
        """工具提供者名称。"""

    def get_tools(self) -> list[Any]:
        """返回 LangChain Tool 列表。"""

    def health_check(self) -> dict[str, Any]:
        """检查工具依赖是否可用。"""


class ToolRegistry:
    """统一管理 Agent 工具，避免工具散落在页面代码中。"""

    def __init__(self) -> None:
        self._providers: dict[str, ToolProvider] = {}

    def register(self, provider: ToolProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"工具提供者已注册：{provider.name}")

        self._providers[provider.name] = provider

    def get_tools(self) -> list[Any]:
        tools: list[Any] = []

        for provider in self._providers.values():
            tools.extend(provider.get_tools())

        return tools

    def health_check(self) -> dict[str, dict[str, Any]]:
        return {
            name: provider.health_check()
            for name, provider in self._providers.items()
        }

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())
