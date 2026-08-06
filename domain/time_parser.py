"""确定性自然语言时间解析器。

本模块不依赖 LangChain 和模型，可以独立做单元测试。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

RELATIVE_DAY_MAP = {
    "今天": 0,
    "明天": 1,
    "后天": 2,
    "昨天": -1,
}

PERIODS = (
    "凌晨",
    "早上",
    "上午",
    "中午",
    "下午",
    "晚上",
)


class TimeParseError(ValueError):
    """时间文本格式错误。"""


class UnsupportedTimeExpression(ValueError):
    """当前版本不支持该时间表达式。"""


def parse_reference_time(
    reference_time: str | None,
    timezone_name: str,
) -> datetime:
    """创建带时区的参考时间。"""

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise TimeParseError(
            f"未知时区：{timezone_name}"
        ) from exc

    if not reference_time:
        return datetime.now(timezone).replace(microsecond=0)

    try:
        parsed = datetime.fromisoformat(
            reference_time.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise TimeParseError(
            "reference_time 必须是 ISO 8601 格式"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    else:
        parsed = parsed.astimezone(timezone)

    return parsed.replace(microsecond=0)


def resolve_date(
    text: str,
    reference: datetime,
) -> tuple[date, list[str]]:
    """从文本中解析日期部分。"""

    rules: list[str] = []

    full_date_match = re.search(
        r"(?P<year>20\d{2})"
        r"(?:-|/|年)"
        r"(?P<month>\d{1,2})"
        r"(?:-|/|月)"
        r"(?P<day>\d{1,2})日?",
        text,
    )

    if full_date_match:
        try:
            result = date(
                int(full_date_match.group("year")),
                int(full_date_match.group("month")),
                int(full_date_match.group("day")),
            )
        except ValueError as exc:
            raise TimeParseError(
                f"无效日期：{full_date_match.group(0)}"
            ) from exc

        rules.append(f"absolute_date:{result.isoformat()}")
        return result, rules

    month_day_match = re.search(
        r"(?P<month>\d{1,2})月"
        r"(?P<day>\d{1,2})[日号]?",
        text,
    )

    if month_day_match:
        month = int(month_day_match.group("month"))
        day = int(month_day_match.group("day"))

        try:
            result = date(reference.year, month, day)
        except ValueError as exc:
            raise TimeParseError(
                f"无效日期：{month}月{day}日"
            ) from exc

        # 约定：未写年份且日期已经过去，则解析为下一年。
        if result < reference.date():
            try:
                result = date(reference.year + 1, month, day)
            except ValueError as exc:
                raise TimeParseError(
                    f"下一年度不存在该日期：{month}月{day}日"
                ) from exc

            rules.append("assumption:past_month_day_rolls_to_next_year")

        rules.append(f"month_day:{month}-{day}")
        return result, rules

    for keyword, offset in RELATIVE_DAY_MAP.items():
        if keyword in text:
            result = reference.date() + timedelta(days=offset)
            rules.append(f"relative_day:{keyword}")
            return result, rules

    offset_match = re.search(
        r"(?P<number>\d+)\s*天\s*(?P<direction>后|前)",
        text,
    )

    if offset_match:
        number = int(offset_match.group("number"))
        direction = offset_match.group("direction")
        offset = number if direction == "后" else -number

        result = reference.date() + timedelta(days=offset)
        rules.append(f"day_offset:{number}天{direction}")
        return result, rules

    weekday_match = re.search(
        r"(?P<prefix>本周|这周|下周|下下周)?"
        r"(?:周|星期)"
        r"(?P<weekday>[一二三四五六日天])",
        text,
    )

    if weekday_match:
        prefix = weekday_match.group("prefix")
        target_weekday = WEEKDAY_MAP[
            weekday_match.group("weekday")
        ]

        current_monday = (
            reference.date()
            - timedelta(days=reference.weekday())
        )

        week_offset_map = {
            "本周": 0,
            "这周": 0,
            "下周": 1,
            "下下周": 2,
        }

        if prefix:
            week_offset = week_offset_map[prefix]
            result = (
                current_monday
                + timedelta(
                    weeks=week_offset,
                    days=target_weekday,
                )
            )
        else:
            # "周五"表示最近一次尚未过去的周五。
            days_ahead = (
                target_weekday - reference.weekday()
            ) % 7

            result = reference.date() + timedelta(
                days=days_ahead
            )

        rules.append(
            f"weekday:{prefix or '最近'}周"
            f"{weekday_match.group('weekday')}"
        )
        return result, rules

    raise UnsupportedTimeExpression(
        "未识别到支持的日期表达式"
    )


def resolve_clock(
    text: str,
) -> tuple[time, str, list[str]]:
    """从文本中解析时间部分。"""

    rules: list[str] = []
    period = next(
        (
            candidate
            for candidate in PERIODS
            if candidate in text
        ),
        None,
    )

    clock_match = re.search(
        r"(?<!\d)"
        r"(?P<hour>\d{1,2})"
        r"(?:"
        r":(?P<colon_minute>\d{1,2})"
        r"|点(?P<point_minute>\d{1,2})?分?"
        r"|时(?P<hour_minute>\d{1,2})?分?"
        r")",
        text,
    )

    if not clock_match:
        rules.append("assumption:no_clock_defaults_to_09:00")
        return time(9, 0), "date", rules

    hour = int(clock_match.group("hour"))
    minute_text = (
        clock_match.group("colon_minute")
        or clock_match.group("point_minute")
        or clock_match.group("hour_minute")
        or "0"
    )
    minute = int(minute_text)

    if minute > 59:
        raise TimeParseError(f"分钟超出范围：{minute}")

    if period:
        rules.append(f"period:{period}")

        if hour > 12:
            raise TimeParseError(
                f"\"{period}\"不能与 {hour} 点组合"
            )

        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        elif period == "中午" and 1 <= hour < 11:
            hour += 12
        elif period == "凌晨" and hour == 12:
            hour = 0
        elif period in {"早上", "上午"} and hour == 12:
            hour = 0

    if hour > 23:
        raise TimeParseError(f"小时超出范围：{hour}")

    rules.append(f"clock:{hour:02d}:{minute:02d}")
    return time(hour, minute), "minute", rules


def parse_natural_time(
    text: str,
    timezone_name: str = "Asia/Shanghai",
    reference_time: str | None = None,
) -> dict[str, Any]:
    """将自然语言时间转换为标准时间。

    该函数不依赖 LangChain 和模型，可以独立测试。
    """

    normalized_text = re.sub(r"\s+", "", text.strip())

    if not normalized_text:
        raise TimeParseError("时间文本不能为空")

    reference = parse_reference_time(
        reference_time,
        timezone_name,
    )

    resolved_date, date_rules = resolve_date(
        normalized_text,
        reference,
    )
    resolved_clock, precision, clock_rules = resolve_clock(
        normalized_text
    )

    timezone = ZoneInfo(timezone_name)

    resolved = datetime.combine(
        resolved_date,
        resolved_clock,
        tzinfo=timezone,
    )

    return {
        "status": "success",
        "source_text": text,
        "normalized_text": normalized_text,
        "timezone": timezone_name,
        "reference_time": reference.isoformat(),
        "resolved_time": resolved.isoformat(),
        "precision": precision,
        "matched_rules": date_rules + clock_rules,
    }
