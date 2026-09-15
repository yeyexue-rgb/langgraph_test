"""（补桥实现）Supervisor 多 Agent 模式占位。

说明：上游仓库未包含本模块；黑盒评测使用 single 模式，
若被调用则明确报错，避免静默失败。
"""
from __future__ import annotations

from typing import Any


def build_supervisor_agent(**kwargs: Any):
    raise NotImplementedError(
        "subagents 模式的 supervisor 模块未包含在本仓库中；"
        "请使用 AGENT_MODE=single 运行。"
    )
