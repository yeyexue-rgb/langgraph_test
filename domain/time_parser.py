"""确定性自然语言时间解析器。

本模块不依赖 LangChain 和模型，可以独立做单元测试。
"""

from __future__ import annotations

import calendar
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
    "大后天": 3,
    "后天": 2,
    "明天": 1,
    "今天": 0,
    "昨天": -1,
    "前天": -2,
    "大前天": -3,
}

PERIODS = (
    "凌晨",
    "早上",
    "上午",
    "中午",
    "下午",
    "晚上",
)

CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_NUM_CHARS = "[一二两三四五六七八九十]"

_CLOCK_RE = re.compile(
    r"(?<!\d)"
    r"(?P<hour>\d{1,2})"
    r"(?:"
    r":(?P<colon_minute>\d{1,2})"
    r"|点(?P<point_minute>\d{1,2})?分?"
    r"|时(?P<hour_minute>\d{1,2})?分?"
    r")"
)


class TimeParseError(ValueError):
    """时间文本格式错误。"""


class UnsupportedTimeExpression(ValueError):
    """当前版本不支持该时间表达式。"""


def _chinese_to_int(text: str) -> int | None:
    """将一位或两位中文数字转换为整数。

    无法识别时返回 None，不抛异常。
    """

    try:
        if text == "十":
            return 10

        if text.startswith("十"):
            return 10 + CHINESE_DIGITS[text[1]]

        if "十" in text:
            tens, _, ones = text.partition("十")
            value = CHINESE_DIGITS[tens] * 10

            if ones:
                value += CHINESE_DIGITS[ones]

            return value

        value = 0

        for char in text:
            value = value * 10 + CHINESE_DIGITS[char]

        return value

    except (KeyError, IndexError):
        return None


def _replace_chinese_number(match: re.Match) -> str:
    """把单个中文数字匹配替换为阿拉伯数字。"""

    value = _chinese_to_int(match.group(1))

    if value is None:
        return match.group(0)

    return f"{value}{match.group(2)}"


def convert_chinese_numerals(text: str) -> str:
    """把中文数字时间与数量转换为阿拉伯数字。

    覆盖三点/十二时/三天/点半/一刻等常见写法，
    无法识别的中文数字原样保留。
    """

    converted = re.sub(
        rf"({_NUM_CHARS}+)(点|时|天)",
        _replace_chinese_number,
        text,
    )
    converted = converted.replace("点半", "点30分")
    converted = converted.replace("点一刻", "点15分")
    converted = converted.replace("点三刻", "点45分")
    return converted


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

    # 按关键词长度降序匹配，避免"大后天"被"后天"提前命中。
    for keyword in sorted(
        RELATIVE_DAY_MAP, key=len, reverse=True
    ):
        offset = RELATIVE_DAY_MAP[keyword]

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

    week_offset_match = re.search(
        r"(?P<number>\d+)\s*个?\s*"
        r"(?:周|星期|礼拜)\s*"
        r"(?P<direction>后|前)",
        text,
    )

    if week_offset_match:
        number = int(week_offset_match.group("number"))
        direction = week_offset_match.group("direction")
        weeks = number if direction == "后" else -number

        result = reference.date() + timedelta(weeks=weeks)
        rules.append(f"week_offset:{number}周{direction}")
        return result, rules

    if "周末" in text:
        # 约定：周末指最近一个尚未过去的周六。
        days_ahead = (5 - reference.weekday()) % 7
        result = reference.date() + timedelta(
            days=days_ahead
        )
        rules.append("weekend:周六")
        return result, rules

    if "月底" in text:
        last_day = calendar.monthrange(
            reference.year, reference.month
        )[1]
        result = date(
            reference.year, reference.month, last_day
        )
        rules.append("month_end:本月最后一天")
        return result, rules

    # 前缀不含"周"字，避免可选组被跳过（历史上
    # "下周一"曾因前缀包含周字而退化为"周一"）。
    weekday_match = re.search(
        r"(?P<prefix>本|这|下下|下)?"
        r"(?:周|星期|礼拜)"
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
            "本": 0,
            "这": 0,
            "下": 1,
            "下下": 2,
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

    clock_match = _CLOCK_RE.search(text)

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

    normalized_text = convert_chinese_numerals(
        re.sub(r"\s+", "", text.strip())
    )

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


RANGE_SEPARATOR_RE = re.compile(r"到|至|~|～|—")


def parse_time_range(
    text: str,
    timezone_name: str = "Asia/Shanghai",
    reference_time: str | None = None,
) -> dict[str, Any]:
    """将自然语言时间段解析为开始/结束时间。

    支持"明天下午3点到5点""明天到后天"等表达，
    分隔符只识别 到/至/~ 等，不与日期中的连字符冲突。
    确定性约定均记录在 matched_rules 中。
    """

    normalized_text = convert_chinese_numerals(
        re.sub(r"\s+", "", text.strip())
    )

    if not normalized_text:
        raise TimeParseError("时间段文本不能为空")

    parts = RANGE_SEPARATOR_RE.split(
        normalized_text, maxsplit=1
    )

    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise UnsupportedTimeExpression(
            "未识别到时间段分隔符（到/至/~）"
        )

    start_text, end_text = parts

    reference = parse_reference_time(
        reference_time,
        timezone_name,
    )

    try:
        start_date, start_rules = resolve_date(
            start_text, reference
        )
    except UnsupportedTimeExpression:
        start_date = reference.date()
        start_rules = [
            "assumption:range_start_defaults_to_today"
        ]

    start_clock, start_precision, start_clock_rules = (
        resolve_clock(start_text)
    )

    rules = start_rules + start_clock_rules

    try:
        end_date, end_date_rules = resolve_date(
            end_text, reference
        )
        end_has_date = True
    except UnsupportedTimeExpression:
        end_date = start_date
        end_date_rules = [
            "assumption:range_end_inherits_start_date"
        ]
        end_has_date = False

    rules += end_date_rules

    end_has_clock = bool(_CLOCK_RE.search(end_text))

    if end_has_clock:
        end_clock, end_precision, end_clock_rules = (
            resolve_clock(end_text)
        )
    else:
        end_clock = time(18, 0)
        end_precision = "date"
        end_clock_rules = [
            "assumption:range_end_defaults_to_18:00"
        ]

    rules += end_clock_rules

    # 约定：开始时间已是下午/晚上而结束时间未写时段且
    # 小时数小于 12 时，推断结束时间也在下午/晚上。
    end_has_period = any(
        candidate in end_text for candidate in PERIODS
    )

    if (
        end_has_clock
        and not end_has_period
        and start_clock.hour >= 12
        and end_clock.hour < 12
    ):
        end_clock = end_clock.replace(
            hour=end_clock.hour + 12
        )
        rules.append("assumption:range_end_pm_inferred")

    timezone = ZoneInfo(timezone_name)

    start_dt = datetime.combine(
        start_date, start_clock, tzinfo=timezone
    )
    end_dt = datetime.combine(
        end_date, end_clock, tzinfo=timezone
    )

    if end_dt <= start_dt:
        if end_has_date:
            raise TimeParseError(
                "时间段的结束时间不能早于开始时间"
            )

        end_dt += timedelta(days=1)
        rules.append(
            "assumption:range_end_rolls_to_next_day"
        )

    precision = (
        "minute"
        if "minute" in (start_precision, end_precision)
        else "date"
    )

    return {
        "status": "success",
        "source_text": text,
        "normalized_text": normalized_text,
        "timezone": timezone_name,
        "reference_time": reference.isoformat(),
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "precision": precision,
        "matched_rules": rules,
    }
