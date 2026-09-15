"""文件领域子 Agent 及其 Supervisor 包装工具。

子 Agent 持有 search_personal_space_files（只读），并在内部挂载
HITL 中间件拦截该业务工具的越界调用——对齐官方 supervisor 文档
第 6 节模式（HumanInTheLoopMiddleware 挂在子 Agent 上拦截业务工具，
中断状态通过 Supervisor 的 checkpointer 持久化）。

包装工具接收结构化参数（复用 FileSearchInput schema），
避免子 Agent 二次解释自然语言时间——
"自然语言时间只解析一次，标准时间只传递一次"
是跨 Agent 数据传递的核心规则。
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool

from agent_core.hitl import build_hitl_middleware, outside_personal_space
from agent_core.subagents.contracts import (
    SubagentResult,
    serialize_subagent_result,
)
from agent_core.subagents.tracing import SubagentTracer
from agent_core.prompt_manager import load_prompt
from providers.file_provider import FileSearchInput


def create_file_specialist_tool(
    *,
    model: Any,
    file_tool: Any,
    tracer: SubagentTracer,
    business_tool_names: set[str],
) -> Any:
    """构建文件子 Agent，并包装为 Supervisor 可调用的工具。

    子 Agent 内部挂载 HITL 中间件拦截 search_personal_space_files
    的越界调用（复用 outside_personal_space 谓词）。中断发生时，
    子 Agent 的 invoke 不会正常返回——而是通过 Supervisor 的
    checkpointer 暂停整个 Supervisor 执行流。
    """

    file_agent = create_agent(
        model=model,
        tools=[file_tool],
        system_prompt=load_prompt("file_specialist"),
        middleware=[
            build_hitl_middleware(
                interrupt_on={
                    "search_personal_space_files": {
                        "allowed_decisions": [
                            "approve",
                            "edit",
                            "reject",
                        ],
                        "when": outside_personal_space,
                    },
                },
                description_prefix=(
                    "文件子 Agent：以下文件查询等待人工审批"
                ),
            ),
        ],
        response_format=ToolStrategy(
            schema=SubagentResult,
            handle_errors=(
                "结果必须符合 SubagentResult 结构。"
                "status 只能使用指定枚举值；summary 不能为空；"
                "没有明确错误代码时 error_code 必须为 null；"
                "不得编造文件数量、文件列表或错误代码。"
            ),
        ),
    )

    @tool(
        "file_specialist",
        args_schema=FileSearchInput,
        description=(
            "查询 D 盘个人空间中的文件。支持按文件名关键词、扩展名、"
            "子目录、修改时间和最大结果数过滤。modified_after 与 "
            "modified_before 必须使用带时区的 ISO 8601 标准时间。"
        ),
    )
    def call_file_specialist(
        keyword: str | None = None,
        extensions: list[str] | None = None,
        relative_directory: str = ".",
        recursive: bool = True,
        modified_after: str | None = None,
        modified_before: str | None = None,
        max_results: int = 50,
    ) -> str:
        """按结构化参数查询个人空间文件。"""

        task = {
            "keyword": keyword,
            "extensions": extensions or [],
            "relative_directory": relative_directory,
            "recursive": recursive,
            "modified_after": modified_after,
            "modified_before": modified_before,
            "max_results": max_results,
        }

        state = file_agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "严格按照以下结构化参数查询文件，"
                            "不要重新解释或修改任何参数值："
                            f"{json.dumps(task, ensure_ascii=False)}"
                        ),
                    }
                ]
            }
        )

        return serialize_subagent_result(
            state,
            expected_agent="file_specialist",
            tracer=tracer,
            business_tool_names=business_tool_names,
        )

    return call_file_specialist
