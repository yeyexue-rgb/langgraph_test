"""domain.time_parser 的单元测试。

不依赖 LangChain 和模型，直接验证解析逻辑。
"""

from __future__ import annotations

import pytest

from domain.time_parser import (
    TimeParseError,
    UnsupportedTimeExpression,
    parse_natural_time,
    parse_time_range,
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

    def test_next_next_week_monday(self) -> None:
        result = parse_natural_time(
            "下下周一",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-17T09:00:00+08:00"

    def test_this_week_friday_with_prefix(self) -> None:
        result = parse_natural_time(
            "本周五",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-07T09:00:00+08:00"

    def test_xingqi_variant(self) -> None:
        result = parse_natural_time(
            "下星期三",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-12T09:00:00+08:00"


class TestExtendedExpressions:
    """扩展表达式：大后天/前天/周偏移/周末/月底。"""

    def test_three_days_later_keyword(self) -> None:
        result = parse_natural_time(
            "大后天",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-06T09:00:00+08:00"

    def test_three_days_later_keyword_beats_houtian(
        self,
    ) -> None:
        result = parse_natural_time(
            "大后天",
            reference_time=REFERENCE,
        )
        assert any(
            "relative_day:大后天" in rule
            for rule in result["matched_rules"]
        )

    def test_day_before_yesterday(self) -> None:
        result = parse_natural_time(
            "前天",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-01T09:00:00+08:00"

    def test_chinese_day_offset(self) -> None:
        result = parse_natural_time(
            "三天后",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-06T09:00:00+08:00"

    def test_week_offset(self) -> None:
        result = parse_natural_time(
            "2周后",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-17T09:00:00+08:00"

    def test_weekend_from_monday(self) -> None:
        # 2026-08-03 是周一，最近的周六是 08-08。
        result = parse_natural_time(
            "周末",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-08T09:00:00+08:00"

    def test_month_end(self) -> None:
        result = parse_natural_time(
            "月底",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-31T09:00:00+08:00"


class TestChineseClock:
    """中文数字时刻解析。"""

    def test_chinese_hour_with_period(self) -> None:
        result = parse_natural_time(
            "明天下午三点",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T15:00:00+08:00"

    def test_half_hour(self) -> None:
        result = parse_natural_time(
            "明天下午三点半",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T15:30:00+08:00"

    def test_quarter_hour(self) -> None:
        result = parse_natural_time(
            "明天上午十点一刻",
            reference_time=REFERENCE,
        )
        assert result["resolved_time"] == "2026-08-04T10:15:00+08:00"


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


class TestTimeRange:
    """时间段解析。"""

    def test_same_day_clock_range_pm_inferred(self) -> None:
        result = parse_time_range(
            "明天下午3点到5点",
            reference_time=REFERENCE,
        )
        assert result["start_time"] == "2026-08-04T15:00:00+08:00"
        assert result["end_time"] == "2026-08-04T17:00:00+08:00"
        assert result["precision"] == "minute"
        assert any(
            "range_end_pm_inferred" in rule
            for rule in result["matched_rules"]
        )

    def test_date_only_range(self) -> None:
        result = parse_time_range(
            "明天到后天",
            reference_time=REFERENCE,
        )
        assert result["start_time"] == "2026-08-04T09:00:00+08:00"
        assert result["end_time"] == "2026-08-05T18:00:00+08:00"
        assert result["precision"] == "date"

    def test_overnight_range_rolls_to_next_day(self) -> None:
        result = parse_time_range(
            "今天23点到凌晨2点",
            reference_time=REFERENCE,
        )
        assert result["start_time"] == "2026-08-03T23:00:00+08:00"
        assert result["end_time"] == "2026-08-04T02:00:00+08:00"
        assert any(
            "range_end_rolls_to_next_day" in rule
            for rule in result["matched_rules"]
        )

    def test_range_with_explicit_dates(self) -> None:
        result = parse_time_range(
            "2026年8月5日9点到2026年8月6日18点",
            reference_time=REFERENCE,
        )
        assert result["start_time"] == "2026-08-05T09:00:00+08:00"
        assert result["end_time"] == "2026-08-06T18:00:00+08:00"

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(TimeParseError, match="结束时间"):
            parse_time_range(
                "2026年8月5日9点到2026年8月1日9点",
                reference_time=REFERENCE,
            )

    def test_no_separator_unsupported(self) -> None:
        with pytest.raises(UnsupportedTimeExpression):
            parse_time_range(
                "某个时间段",
                reference_time=REFERENCE,
            )

    def test_empty_text_raises(self) -> None:
        with pytest.raises(TimeParseError, match="不能为空"):
            parse_time_range("   ", reference_time=REFERENCE)
