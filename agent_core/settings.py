"""Agent 模型与运行配置加载。

提示词内容已外置到项目根目录的 prompts/ 文件夹
（由 agent_core.prompt_manager 统一加载），
调整提示词不需要修改本模块代码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agent_core.prompt_manager import load_prompt


AGENT_MODES = ("single", "subagents")


@dataclass(frozen=True)
class AgentSettings:
    """Agent 模型与运行配置。"""

    model_name: str
    api_key: str
    base_url: str
    temperature: float
    system_prompt: str
    agent_mode: str = "single"


def load_agent_settings() -> AgentSettings:
    """从环境变量加载 Agent 配置。

    AGENT_MODE 控制架构模式（灰度开关）：
    - single：单 Agent 直接持有业务工具（回归基线）；
    - subagents：Supervisor + 领域子 Agent（Multi-Agent 实验）。

    system_prompt 从 prompts/ 目录加载（场景名 system），
    提示词目录可通过 AGENT_PROMPT_DIR 环境变量覆盖。
    """

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    base_url = os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).strip()
    model_name = os.getenv(
        "MODEL_NAME",
        "qwen3.7-max",
    ).strip()

    agent_mode = os.getenv("AGENT_MODE", "single").strip().lower()

    if agent_mode not in AGENT_MODES:
        raise ValueError(
            f"AGENT_MODE 必须是 {AGENT_MODES} 之一：{agent_mode!r}"
        )

    return AgentSettings(
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        system_prompt=load_prompt("system"),
        agent_mode=agent_mode,
    )
