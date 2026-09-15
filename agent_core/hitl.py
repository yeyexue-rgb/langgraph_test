"""HITL（Human-in-the-Loop）人工审批中间件配置。

三层防线设计：
1. 提示词层：settings.py 的规则（概率性约束，引导模型不越界）；
2. 工具层：file_provider._safe_directory 路径穿越防护（硬约束，
   越界调用即使执行也返回 access_denied）；
3. 审批层：本模块的 HITL 中间件——可疑调用在执行前被拦截，
   等待人工 approve / edit / reject，无决策则不执行。

决策类型（与 langchain HumanInTheLoopMiddleware 契约一致）：
- approve：按原始参数执行工具；
- edit：修改 edited_action（name/args）后执行；
- reject：跳过执行，向模型返回 status="error" 的拒绝 ToolMessage；
- respond：人类直接代替工具回答（status="success"）。
  ⚠️ respond 会伪装成成功结果，仅适合 ask_user 类工具，
  本项目对文件查询不启用。

恢复格式：Command(resume={"decisions": [{"type": ...}, ...]})，
决策数量与顺序必须与待审批操作一一对应。
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware


FILE_SEARCH_TOOL_NAME = "search_personal_space_files"

# 不允许 respond：它会把人类消息伪装成 status="success" 的工具结果，
# 诱导模型认为查询成功，不适合用于有边界约束的文件查询。
ALLOWED_FILE_SEARCH_DECISIONS = ["approve", "edit", "reject"]


def outside_personal_space(request: Any) -> bool:
    """when 谓词：只拦截试图越出个人空间的文件查询。

    返回 True 表示需要人工审批；False 表示自动放行。

    谓词只做"是否可疑"的快速判断，不替代工具层安全校验；
    即使谓词漏判，_safe_directory 仍会兜底返回 access_denied，
    形成"审批层 + 工具层"双保险。
    """

    tool_call = getattr(request, "tool_call", None)
    if not isinstance(tool_call, dict):
        return False

    args = tool_call.get("args")
    if not isinstance(args, dict):
        return False

    relative_directory = str(args.get("relative_directory", "")).strip()

    # 路径穿越
    if ".." in relative_directory:
        return True

    # 盘符绝对路径（大小写不敏感，兼容正反斜杠）
    upper = relative_directory.upper()
    if "C:" in upper or "D:" in upper or "E:" in upper:
        return True

    # 类 Unix 绝对路径 / UNC 路径
    if relative_directory.startswith(("/", "\\")):
        return True

    return False


PERSONAL_SPACE_INTERRUPT_ON: dict[str, Any] = {
    FILE_SEARCH_TOOL_NAME: {
        "allowed_decisions": ALLOWED_FILE_SEARCH_DECISIONS,
        "when": outside_personal_space,
    },
}


def build_hitl_middleware(
    interrupt_on: dict[str, Any] | None = None,
    description_prefix: str = "个人文件助理：以下操作等待人工审批",
) -> HumanInTheLoopMiddleware:
    """构建 HITL 中间件。

    默认拦截试图越出个人空间的文件查询；
    可通过 interrupt_on 覆盖（如测试传 {"tool": True} 全量拦截）。
    """

    return HumanInTheLoopMiddleware(
        interrupt_on=interrupt_on or PERSONAL_SPACE_INTERRUPT_ON,
        description_prefix=description_prefix,
    )
