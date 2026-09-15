"""providers.time_provider 的工具层测试。

验证 @tool 装饰后的行为，不经过 Agent。
"""

from __future__ import annotations

import json

import pytest

from providers.time_provider import (
    TimeToolProvider,
    date_add,
    date_diff,
    get_current_time,
    parse_natural_datetime,
    parse_time_range_tool,
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


class TestParseTimeRangeTool:
    """parse_time_range 时间段工具。"""

    def test_success(self) -> None:
        raw = parse_time_range_tool.invoke(
            {
                "text": "明天下午3点到5点",
                "reference_time": REFERENCE,
            }
        )
        result = json.loads(raw)

        assert result["status"] == "success"
        assert result["start_time"] == "2026-08-04T15:00:00+08:00"
        assert result["end_time"] == "2026-08-04T17:00:00+08:00"

    def test_unsupported(self) -> None:
        raw = parse_time_range_tool.invoke(
            {
                "text": "某个时间段",
                "reference_time": REFERENCE,
            }
        )
        result = json.loads(raw)

        assert result["status"] == "unsupported"

    def test_end_before_start_is_error(self) -> None:
        raw = parse_time_range_tool.invoke(
            {
                "text": "2026年8月5日9点到2026年8月1日9点",
                "reference_time": REFERENCE,
            }
        )
        result = json.loads(raw)

        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_TIME_EXPRESSION"


class TestGetCurrentTimeTool:
    """get_current_time 当前时间工具。"""

    def test_success(self) -> None:
        result = json.loads(get_current_time.invoke({}))

        assert result["status"] == "success"
        assert result["timezone"] == "Asia/Shanghai"
        assert result["weekday"].startswith("周")
        assert "T" in result["current_time"]

    def test_invalid_timezone(self) -> None:
        result = json.loads(
            get_current_time.invoke(
                {"timezone_name": "Mars/Olympus"}
            )
        )

        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_TIMEZONE"


class TestDateAddTool:
    """date_add 日期加减工具。"""

    def test_add_days(self) -> None:
        result = json.loads(
            date_add.invoke(
                {"base_date": "2026-08-01", "days": 5}
            )
        )

        assert result["status"] == "success"
        assert result["result_date"] == "2026-08-06"
        assert result["weekday"] == "周四"

    def test_subtract_days(self) -> None:
        result = json.loads(
            date_add.invoke(
                {"base_date": "2026-08-01", "days": -1}
            )
        )

        assert result["result_date"] == "2026-07-31"

    def test_default_base_is_today(self) -> None:
        result = json.loads(date_add.invoke({"days": 0}))

        assert result["status"] == "success"
        assert result["base_date"] == result["result_date"]

    def test_invalid_base_date(self) -> None:
        result = json.loads(
            date_add.invoke(
                {"base_date": "2026/08/01", "days": 1}
            )
        )

        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_DATE"


class TestDateDiffTool:
    """date_diff 日期差工具。"""

    def test_positive_diff(self) -> None:
        result = json.loads(
            date_diff.invoke(
                {"date_a": "2026-08-01", "date_b": "2026-09-01"}
            )
        )

        assert result["status"] == "success"
        assert result["diff_days"] == 31
        assert result["weekday_a"] == "周六"
        assert result["weekday_b"] == "周二"

    def test_negative_diff(self) -> None:
        result = json.loads(
            date_diff.invoke(
                {"date_a": "2026-09-01", "date_b": "2026-08-01"}
            )
        )

        assert result["diff_days"] == -31

    def test_invalid_date(self) -> None:
        result = json.loads(
            date_diff.invoke(
                {
                    "date_a": "2026/08/01",
                    "date_b": "2026-08-01",
                }
            )
        )

        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_DATE"


class TestTimeToolProvider:
    """TimeToolProvider 集成测试。"""

    EXPECTED_TOOL_NAMES = {
        "parse_natural_datetime",
        "parse_time_range",
        "get_current_time",
        "date_add",
        "date_diff",
    }

    def test_provider_name(self) -> None:
        provider = TimeToolProvider()
        assert provider.name == "time"

    def test_get_tools_returns_time_matrix(self) -> None:
        provider = TimeToolProvider()
        tools = provider.get_tools()

        assert len(tools) == 5
        assert {t.name for t in tools} == self.EXPECTED_TOOL_NAMES
        assert tools[0] is parse_natural_datetime

    def test_health_check_healthy(self) -> None:
        provider = TimeToolProvider()
        health = provider.health_check()

        assert health["status"] == "healthy"
        assert health["tool_count"] == 5
        assert health["sample_result"] == "2026-08-04T15:00:00+08:00"
