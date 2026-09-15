"""（补桥实现）Agent 结构化输出模型。

契约：AgentResponse 需提供 answer（非空）、status（枚举）、error_code；
并提供 model_dump()（pydantic 默认）。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    """Agent 最终结构化响应。"""

    status: Literal["success", "error"] = Field(
        default="success",
        description="success=正常完成；error=无法完成",
    )
    answer: str = Field(
        min_length=1,
        description="给用户的最终回答（简体中文，不得编造工具未返回的信息）",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="仅当 status=error 时填写；无明确错误代码时必须为 null",
    )
