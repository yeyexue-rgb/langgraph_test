"""Agent 最终结构化响应契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentResponse(BaseModel):
    """Agent 每轮任务结束后的标准结果。

    Schema 只能约束格式（字段存在、类型正确、枚举合法、非空），
    不能保证业务结论真实。业务正确性需要结合工具轨迹验证。
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    status: Literal[
        "success",
        "partial_success",
        "needs_clarification",
        "error",
    ] = Field(
        description=(
            "任务状态：完全完成使用 success；"
            "只完成部分任务使用 partial_success；"
            "需要用户补充信息使用 needs_clarification；"
            "任务执行失败使用 error。"
        )
    )

    answer: str = Field(
        min_length=1,
        description="展示给用户的最终中文回答。",
    )

    error_code: str | None = Field(
        default=None,
        description=(
            "工具明确返回错误代码时填写；"
            "工具未返回错误代码时必须为 null。"
        ),
    )

    needs_human_review: bool = Field(
        default=False,
        description="当前结果是否需要人工复核。",
    )
