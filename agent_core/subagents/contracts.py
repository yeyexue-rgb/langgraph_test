"""子 Agent 内部结果契约。

Supervisor 与子 Agent 之间使用 SubagentResult 传递结构化结果：
- agent_name 标识结果来源，防止模型填错身份；
- status 与业务工具状态对齐（success/unsupported/access_denied/error）；
- data 携带领域数据（如 resolved_time / files）；
- 外部接口继续使用 AgentResponse，本契约仅在 Multi-Agent 内部使用。

关键原则：模型负责表达结果，程序负责记录事实。
tools_used 与嵌套轨迹由 SubagentTracer 从真实消息提取，
不信任模型自述。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_core.subagents.tracing import SubagentTracer


class SubagentResult(BaseModel):
    """子 Agent 返回给 Supervisor 的内部结果。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    agent_name: Literal[
        "time_specialist",
        "file_specialist",
        "sql_specialist",
    ] = Field(
        description="产出该结果的子 Agent 名称。",
    )

    status: Literal[
        "success",
        "unsupported",
        "access_denied",
        "error",
    ] = Field(
        description=(
            "任务状态：成功使用 success；不支持的表达使用 "
            "unsupported；访问被拒绝使用 access_denied；"
            "执行失败使用 error。"
        )
    )

    summary: str = Field(
        min_length=1,
        description="给 Supervisor 的中文结果摘要。",
    )

    data: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "领域数据对象（必须是键值对，不能是数组）："
            "时间子 Agent 至少包含 resolved_time 与 timezone；"
            "文件子 Agent 至少包含 count 与 files；"
            "SQL 子 Agent 至少包含 query（执行的 SQL）与 "
            "results（查询结果）。"
        ),
    )

    error_code: str | None = Field(
        default=None,
        description=(
            "工具明确返回错误代码时填写；"
            "未返回错误代码时必须为 null。"
        ),
    )


def subagent_handle_errors(exception: Exception) -> str:
    """ToolStrategy 的 handle_errors 回调：附上具体校验错误。

    静态文案不包含失败原因，模型无法自我修正，可能反复提交同样的
    非法结构，最终以纯文本收尾导致 structured_response 缺失、
    整个子 Agent 被降级为 INVALID_SUBAGENT_RESULT。
    """

    return (
        "结果必须符合 SubagentResult 结构，请修正后重新提交："
        "agent_name 与 status 只能使用指定枚举值；summary 不能为空；"
        "data 必须是键值对对象，不能是数组；"
        "没有明确错误代码时 error_code 必须为 null；"
        "不得编造查询结果或错误代码。"
        f"具体校验错误：{exception}"
    )


def serialize_subagent_result(
    state: Any,
    *,
    expected_agent: str,
    tracer: SubagentTracer,
    business_tool_names: set[str],
) -> str:
    """将子 Agent 的 invoke 状态转换为 Supervisor 可用的工具结果。

    职责：
    1. 记录嵌套轨迹（无论结构化结果是否有效）；
    2. 校验 structured_response 是否为 SubagentResult；
    3. 校验 agent_name 是否与 expected_agent 一致；
    4. 任何校验失败都降级为 error 结果，禁止把垃圾传给 Supervisor。

    返回 JSON 字符串（Supervisor 的 ToolMessage 内容）。
    """

    # 先记录嵌套轨迹：即使结构化结果损坏，真实执行轨迹仍然要留痕。
    tracer.record(expected_agent, state, business_tool_names)

    structured = (
        state.get("structured_response")
        if isinstance(state, dict)
        else None
    )

    if not isinstance(structured, SubagentResult):
        fallback = SubagentResult(
            agent_name=expected_agent,  # type: ignore[arg-type]
            status="error",
            summary="子 Agent 未返回有效的结构化结果。",
            error_code="INVALID_SUBAGENT_RESULT",
        )
        return fallback.model_dump_json()

    if structured.agent_name != expected_agent:
        fallback = SubagentResult(
            agent_name=expected_agent,  # type: ignore[arg-type]
            status="error",
            summary=(
                f"子 Agent 返回了错误的身份标识：{structured.agent_name}。"
            ),
            error_code="INVALID_SUBAGENT_NAME",
        )
        return fallback.model_dump_json()

    return structured.model_dump_json()


def parse_subagent_payload(content: str) -> dict[str, Any]:
    """解析 SubagentResult 的 JSON 字符串（测试与展示用）。

    解析失败时返回空 dict，不抛异常。
    """

    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}

    return payload if isinstance(payload, dict) else {}
