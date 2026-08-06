"""domain.time_parser 的单元测试。

不依赖 LangChain 和模型，直接验证解析逻辑。
"""

from __future__ import annotations

import pytest

from domain.time_parser import (
    TimeParseError,
    UnsupportedTimeExpression,
    parse_natural_time,
)


REFERENCE = "2026-08-03T10:00:00+08:00"


class TestRelativeDay:
    """相对日期解析。"""

    def test_today(self) -> None:
        result = parse_natural_time(
            "今天",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-03T09:00:00+08:00"
        assert result["precision"] == "date"

    def test_tomorrow_afternoon(self) -> None:
        result = parse_natural_time(
            "明天下午3点",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T15:00:00+08:00"
        assert result["precision"] == "minute"

    def test_day_offset(self) -> None:
        result = parse_natural_time(
            "3天后",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-06T09:00:00+08:00"

    def test_yesterday(self) -> None:
        result = parse_natural_time(
            "昨天",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-02T09:00:00+08:00"


class TestWeekday:
    """星期解析。"""

    def test_next_friday(self) -> None:
        # 2026-08-03 是周一，最近的周五是 08-07
        result = parse_natural_time(
            "周五",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-07T09:00:00+08:00"

    def test_next_week_monday(self) -> None:
        result = parse_natural_time(
            "下周一",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-10T09:00:00+08:00"

    def test_this_week_sunday(self) -> None:
        result = parse_natural_time(
            "本周日",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-09T09:00:00+08:00"


class TestAbsoluteDate:
    """绝对日期解析。"""

    def test_full_date(self) -> None:
        result = parse_natural_time(
            "2026年12月25日",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-12-25T09:00:00+08:00"

    def test_month_day(self) -> None:
        result = parse_natural_time(
            "8月15日",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-15T09:00:00+08:00"

    def test_past_month_day_rolls_to_next_year(self) -> None:
        result = parse_natural_time(
            "1月1日",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2027-01-01T09:00:00+08:00"


class TestClock:
    """时间部分解析。"""

    def test_colon_format(self) -> None:
        result = parse_natural_time(
            "明天14:30",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T14:30:00+08:00"

    def test_point_format_with_minute(self) -> None:
        result = parse_natural_time(
            "明天上午9点30分",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T09:30:00+08:00"

    def test_evening_pm_conversion(self) -> None:
        result = parse_natural_time(
            "明天晚上8点",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T20:00:00+08:00"

    def test_noon_conversion(self) -> None:
        result = parse_natural_time(
            "明天中午12点",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T12:00:00+08:00"

    def test_period_with_hour_over_12_raises(self) -> None:
        with pytest.raises(TimeParseError):
            parse_natural_time(
                "明天下午15点",
                reference_time=REFERENCE,
            )


class TestErrorHandling:
    """异常场景。"""

    def test_empty_text(self) -> None:
        with pytest.raises(TimeParseError, match="不能为空"):
            parse_natural_time("   ", reference_time=REFERENCE)

    def test_unsupported_expression(self) -> None:
        with pytest.raises(UnsupportedTimeExpression):
            parse_natural_time(
                "某个时候",
                reference_time=REFERENCE,
            )

    def test_unknown_timezone(self) -> None:
        with pytest.raises(TimeParseError, match="未知时区"):
            parse_natural_time(
                "明天",
                timezone_name="Mars/Olympus",
                reference_time=REFERENCE,
            )


class TestDeterminism:
    """确定性：相同参数和种子应生成相同结果。"""

    def test_same_input_same_output(self) -> None:
        r1 = parse_natural_time(
            "下周五下午3点",
            reference_time=REFERENCE,
        )
        r2 = parse_natural_time(
            "下周五下午3点",
            reference_time=REFERENCE,
        )
        assert r1["resolved_time"] == r2["resolved_time"]

    def test_matched_rules_recorded(self) -> None:
        result = parse_natural_time(
            "明天下午3点",
            reference_time=REFERENCE,
        )
        assert any("period:下午" in r for r in result["matched_rules"])
        assert any("clock:15:00" in r for r in result["matched_rules"])
