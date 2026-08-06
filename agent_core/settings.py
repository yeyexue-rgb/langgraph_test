"""Agent 模型与系统提示词配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_SYSTEM_PROMPT = """
你是一个面向测试工程师的 AI 助手。

当前拥有两个工具：
1. parse_natural_datetime：解析自然语言时间；
2. search_personal_space_files：查找个人空间中的文件。

你可以使用当前 thread_id 中的历史消息理解用户追问。

必须遵守以下规则：
1. 时间计算必须使用时间解析工具；
2. 文件查询必须使用文件查找工具；
3. 按自然语言时间筛选文件时，必须先解析时间，再查询文件；
4. 文件工具只能访问 D:\\个人空间；
5. 不得声称读取、修改或删除了文件；
6. 用户要求访问其他目录时，应明确拒绝；
7. 工具返回 access_denied、unsupported 或 error 时，
   不得宣称操作成功；
8. 不得由模型自行计算相对日期；
9. 可以继承当前线程中明确的查询条件；
10. 指代不明确时要求用户补充信息；
11. 不得假设或引用其他线程的信息；
12. 最终回答必须忠实于工具返回结果。
""".strip()


@dataclass(frozen=True)
class AgentSettings:
    """Agent 模型与运行配置。"""

    model_name: str
    api_key: str
    base_url: str
    temperature: float
    system_prompt: str


def load_agent_settings() -> AgentSettings:
    """从环境变量加载 Agent 配置。"""

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    base_url = os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).strip()
    model_name = os.getenv(
        "MODEL_NAME",
        "qwen3.7-max",
    ).strip()

    return AgentSettings(
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
    )
