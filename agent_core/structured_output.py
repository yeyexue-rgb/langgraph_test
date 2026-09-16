"""（补桥实现）Agent 结构化输出模型。

契约：AgentResponse 需提供 answer（非空）、status（枚举）、error_code、
needs_human_review（bool）；禁止额外字段；
并提供 model_dump()（pydantic 默认）。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AgentResponse(BaseModel):
    """Agent 最终结构化响应。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "success",
        "partial_success",
        "needs_clarification",
        "error",
    ] = Field(
        default="success",
        description=(
            "success=目标完整完成；partial_success=部分完成；"
            "needs_clarification=需要用户补充信息；error=无法完成"
        ),
    )
    answer: str = Field(
        min_length=1,
        description="给用户的最终回答（简体中文，不得编造工具未返回的信息）",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="仅当 status=error 时填写；无明确错误代码时必须为 null",
    )
    needs_human_review: bool = Field(
        default=False,
        description="仅当结果存在风险、歧义或需要人工确认时为 true",
    )


def agent_response_handle_errors(exception: Exception) -> str:
    """ToolStrategy 的 handle_errors 回调：附上具体校验错误。

    静态文案不包含失败原因，模型无法针对性自我修正；
    附上 pydantic 校验错误后模型可以在下一轮直接改对。
    """

    return (
        "最终响应不符合规定格式，请修正后重新提交："
        "status 必须使用指定枚举值；answer 不能为空；"
        "没有明确错误代码时 error_code 必须为 null；"
        "不得编造工具或子 Agent 的执行结果或错误代码。"
        f"具体校验错误：{exception}"
    )
