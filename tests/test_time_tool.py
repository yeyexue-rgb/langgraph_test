"""providers.time_provider 的工具层测试。

验证 @tool 装饰后的行为，不经过 Agent。
"""

from __future__ import annotations

import json

import pytest

from providers.time_provider import (
    TimeToolProvider,
    parse_natural_datetime,
)


REFERENCE = "2026-08-03T10:00:00+08:00"


class TestParseNaturalDatetimeTool:
    """parse_natural_datetime 工具函数。"""

    def test_success(self) -> None:
        raw = parse_natural_datetime.invoke(
            {
                "text": "明天下午3点",
                "reference_time": REFERENCE,
            }
        )
        result = json.loads(raw)

        assert result["status"] == "success"
        assert result["resolved_time"] == "2026-08-04T15:00:00+08:00"
        assert result["timezone"] == "Asia/Shanghai"
        assert result["source_text"] == "明天下午3点"

    def test_unsupported(self) -> None:
        raw = parse_natural_datetime.invoke(
            {
                "text": "某个时候",
                "reference_time": REFERENCE,
            }
        )
        result = json.loads(raw)

        assert result["status"] == "unsupported"
        assert "source_text" in result

    def test_invalid_time_expression(self) -> None:
        raw = parse_natural_datetime.invoke(
            {
                "text": "明天下午15点",
                "reference_time": REFERENCE,
            }
        )
        result = json.loads(raw)

        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_TIME_EXPRESSION"

    def test_default_timezone(self) -> None:
        raw = parse_natural_datetime.invoke(
            {
                "text": "今天",
                "reference_time": REFERENCE,
            }
        )
        result = json.loads(raw)

        assert result["timezone"] == "Asia/Shanghai"


class TestTimeToolProvider:
    """TimeToolProvider 集成测试。"""

    def test_provider_name(self) -> None:
        provider = TimeToolProvider()
        assert provider.name == "time"

    def test_get_tools_returns_one_tool(self) -> None:
        provider = TimeToolProvider()
        tools = provider.get_tools()
        assert len(tools) == 1
        assert tools[0] is parse_natural_datetime

    def test_health_check_healthy(self) -> None:
        provider = TimeToolProvider()
        health = provider.health_check()

        assert health["status"] == "healthy"
        assert health["tool_count"] == 1
        assert health["sample_result"] == "2026-08-04T15:00:00+08:00"
