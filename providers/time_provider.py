"""自然语言时间解析的 LangChain Tool 与 Provider。"""

from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field

from domain.time_parser import (
    TimeParseError,
    UnsupportedTimeExpression,
    parse_natural_time,
)


class ParseTimeInput(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "需要解析的自然语言时间，例如"
            "\"明天下午3点\"或\"下周一上午9点\""
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

    适用于"明天下午3点""3天后""下周一上午9点"等表达。
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


class TimeToolProvider:
    """自然语言时间工具提供者。"""

    @property
    def name(self) -> str:
        return "time"

    def get_tools(self) -> list[Any]:
        return [parse_natural_datetime]

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
                "tool_count": 1,
                "sample_result": result["resolved_time"],
            }

        except Exception as exc:
            return {
                "status": "unhealthy",
                "tool_count": 1,
                "message": str(exc),
            }
