"""自然语言时间解析的 LangChain Tool 与 Provider。

工具矩阵：
- parse_natural_datetime：单点时间解析（相对/绝对表达）；
- parse_time_range：时间段解析，返回 start/end；
- get_current_time：获取当前系统时间；
- date_add：某个日期加减若干天；
- date_diff：两个日期相差的天数。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.tools import tool
from pydantic import BaseModel, Field

from domain.time_parser import (
    TimeParseError,
    UnsupportedTimeExpression,
    parse_natural_time,
    parse_time_range,
)


WEEKDAY_NAMES = (
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
)


class ParseTimeInput(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "需要解析的自然语言时间，例如"
            "\"明天下午3点\"\"下周一上午9点\""
            "\"大后天\"\"周末\"\"月底\""
        ),
    )
    timezone_name: str = Field(
        default="Asia/Shanghai",
        min_length=1,
        max_length=100,
        description="IANA 时区名称",
    )
    reference_time: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "用于计算相对日期的参考时间。"
            "只有用户明确指定参考时间或执行测试回放时才传入；"
            "格式必须是 ISO 8601"
        ),
    )


@tool(args_schema=ParseTimeInput)
def parse_natural_datetime(
    text: str,
    timezone_name: str = "Asia/Shanghai",
    reference_time: str | None = None,
) -> str:
    """将自然语言日期时间解析为标准 ISO 8601 时间。

    适用于"明天下午3点""3天后""下周一上午9点"
    "大后天""周末""月底""下午三点半"等表达。
    不支持的表达会明确返回 unsupported，禁止自行猜测。
    """

    try:
        result = parse_natural_time(
            text=text,
            timezone_name=timezone_name,
            reference_time=reference_time,
        )
        return json.dumps(result, ensure_ascii=False)

    except UnsupportedTimeExpression as exc:
        return json.dumps(
            {
                "status": "unsupported",
                "source_text": text,
                "message": str(exc),
            },
            ensure_ascii=False,
        )

    except TimeParseError as exc:
        return json.dumps(
            {
                "status": "error",
                "source_text": text,
                "error_code": "INVALID_TIME_EXPRESSION",
                "message": str(exc),
            },
            ensure_ascii=False,
        )

    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "source_text": text,
                "error_code": "INTERNAL_ERROR",
                "message": f"时间解析失败：{exc}",
            },
            ensure_ascii=False,
        )


class TimeRangeInput(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "需要解析的自然语言时间段，例如"
            "\"明天下午3点到5点\"或\"明天到后天\""
        ),
    )
    timezone_name: str = Field(
        default="Asia/Shanghai",
        min_length=1,
        max_length=100,
        description="IANA 时区名称",
    )
    reference_time: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "用于计算相对日期的参考时间。"
            "只有用户明确指定参考时间或执行测试回放时才传入；"
            "格式必须是 ISO 8601"
        ),
    )


@tool("parse_time_range", args_schema=TimeRangeInput)
def parse_time_range_tool(
    text: str,
    timezone_name: str = "Asia/Shanghai",
    reference_time: str | None = None,
) -> str:
    """将自然语言时间段解析为开始与结束两个标准时间。

    适用于"明天下午3点到5点""明天到后天"等包含起止的区间表达；
    单点时间请改用 parse_natural_datetime。
    """

    try:
        result = parse_time_range(
            text=text,
            timezone_name=timezone_name,
            reference_time=reference_time,
        )
        return json.dumps(result, ensure_ascii=False)

    except UnsupportedTimeExpression as exc:
        return json.dumps(
            {
                "status": "unsupported",
                "source_text": text,
                "message": str(exc),
            },
            ensure_ascii=False,
        )

    except TimeParseError as exc:
        return json.dumps(
            {
                "status": "error",
                "source_text": text,
                "error_code": "INVALID_TIME_EXPRESSION",
                "message": str(exc),
            },
            ensure_ascii=False,
        )

    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "source_text": text,
                "error_code": "INTERNAL_ERROR",
                "message": f"时间段解析失败：{exc}",
            },
            ensure_ascii=False,
        )


class CurrentTimeInput(BaseModel):
    timezone_name: str = Field(
        default="Asia/Shanghai",
        min_length=1,
        max_length=100,
        description="IANA 时区名称",
    )


@tool(args_schema=CurrentTimeInput)
def get_current_time(
    timezone_name: str = "Asia/Shanghai",
) -> str:
    """获取当前系统时间。

    适用于"现在几点""今天星期几"等问题，
    返回 ISO 8601 时间、日期与星期。
    """

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return json.dumps(
            {
                "status": "error",
                "error_code": "INVALID_TIMEZONE",
                "message": f"未知时区：{timezone_name}",
            },
            ensure_ascii=False,
        )

    now = datetime.now(timezone).replace(microsecond=0)

    return json.dumps(
        {
            "status": "success",
            "current_time": now.isoformat(),
            "date": now.date().isoformat(),
            "weekday": WEEKDAY_NAMES[now.weekday()],
            "timezone": timezone_name,
        },
        ensure_ascii=False,
    )


class DateAddInput(BaseModel):
    base_date: str | None = Field(
        default=None,
        max_length=20,
        description=(
            "基准日期，格式 YYYY-MM-DD；"
            "不传则使用当前时区的今天"
        ),
    )
    days: int = Field(
        description="偏移天数，负数表示往前推",
        ge=-3660,
        le=3660,
    )
    timezone_name: str = Field(
        default="Asia/Shanghai",
        min_length=1,
        max_length=100,
        description="IANA 时区名称，仅影响缺省基准日期",
    )


@tool(args_schema=DateAddInput)
def date_add(
    base_date: str | None = None,
    days: int = 0,
    timezone_name: str = "Asia/Shanghai",
) -> str:
    """计算某个日期加减若干天后的日期。

    适用于"今天是几号，5天后呢"这类日期偏移计算；
    自然语言相对时间请改用 parse_natural_datetime。
    """

    if base_date:
        try:
            start = date.fromisoformat(base_date)
        except ValueError:
            return json.dumps(
                {
                    "status": "error",
                    "error_code": "INVALID_DATE",
                    "message": (
                        "base_date 必须是 YYYY-MM-DD 格式"
                    ),
                },
                ensure_ascii=False,
            )
    else:
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return json.dumps(
                {
                    "status": "error",
                    "error_code": "INVALID_TIMEZONE",
                    "message": f"未知时区：{timezone_name}",
                },
                ensure_ascii=False,
            )

        start = datetime.now(timezone).date()

    result = start + timedelta(days=days)

    return json.dumps(
        {
            "status": "success",
            "base_date": start.isoformat(),
            "days": days,
            "result_date": result.isoformat(),
            "weekday": WEEKDAY_NAMES[result.weekday()],
        },
        ensure_ascii=False,
    )


class DateDiffInput(BaseModel):
    date_a: str = Field(
        min_length=8,
        max_length=20,
        description="起始日期，格式 YYYY-MM-DD",
    )
    date_b: str = Field(
        min_length=8,
        max_length=20,
        description="目标日期，格式 YYYY-MM-DD",
    )


@tool(args_schema=DateDiffInput)
def date_diff(date_a: str, date_b: str) -> str:
    """计算两个日期相差的天数（date_b - date_a）。

    适用于"两个日期还差几天"类问题，
    结果为负数表示 date_b 在 date_a 之前。
    """

    try:
        start = date.fromisoformat(date_a)
        end = date.fromisoformat(date_b)
    except ValueError:
        return json.dumps(
            {
                "status": "error",
                "error_code": "INVALID_DATE",
                "message": (
                    "date_a/date_b 必须是 YYYY-MM-DD 格式"
                ),
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "status": "success",
            "date_a": start.isoformat(),
            "date_b": end.isoformat(),
            "diff_days": (end - start).days,
            "weekday_a": WEEKDAY_NAMES[start.weekday()],
            "weekday_b": WEEKDAY_NAMES[end.weekday()],
        },
        ensure_ascii=False,
    )


class TimeToolProvider:
    """自然语言时间工具提供者。"""

    @property
    def name(self) -> str:
        return "time"

    def get_tools(self) -> list[Any]:
        return [
            parse_natural_datetime,
            parse_time_range_tool,
            get_current_time,
            date_add,
            date_diff,
        ]

    def health_check(self) -> dict[str, Any]:
        try:
            result = parse_natural_time(
                text="明天下午3点",
                timezone_name="Asia/Shanghai",
                reference_time="2026-08-03T10:00:00+08:00",
            )

            healthy = (
                result["resolved_time"]
                == "2026-08-04T15:00:00+08:00"
            )

            return {
                "status": (
                    "healthy" if healthy else "unhealthy"
                ),
                "tool_count": len(self.get_tools()),
                "sample_result": result["resolved_time"],
            }

        except Exception as exc:
            return {
                "status": "unhealthy",
                "tool_count": len(self.get_tools()),
                "message": str(exc),
            }
