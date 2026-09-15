"""提示词轻量外置管理。

提示词以 .md 文件形式存放在项目根目录的 prompts/ 下
（一个场景一个文件，文件名即场景名），由 PromptManager 统一加载：

- 调整提示词只需修改 .md 文件，不必改动代码、不必重跑无关测试；
- 测试可通过 PromptManager(directory) 注入自定义目录，实现场景隔离；
- AGENT_PROMPT_DIR 环境变量可覆盖默认目录，便于切换不同提示词
  版本做对照实验。

设计边界（轻量外置，刻意不做重）：
- 不做版本号管理与热加载监听；每次加载都从磁盘读取，
  文件改动后下一次构建 Agent 自然拿到最新内容；
- 不做模板渲染，提示词即所见即所得的纯文本。
"""

from __future__ import annotations

import os
from pathlib import Path


PROMPT_DIR_ENV = "AGENT_PROMPT_DIR"

# 项目必备提示词场景，prompts/ 下必须存在同名 .md 文件。
PROMPT_NAMES = (
    "system",
    "supervisor",
    "time_specialist",
    "file_specialist",
    "sql_specialist",
)

PROJECT_PROMPT_DIR = (
    Path(__file__).resolve().parent.parent / "prompts"
)


class PromptNotFoundError(FileNotFoundError):
    """提示词文件不存在或内容为空。"""


class PromptManager:
    """按场景名加载提示词内容。"""

    def __init__(
        self,
        directory: str | Path | None = None,
    ) -> None:
        """初始化提示词目录。

        优先级：显式传入的 directory > AGENT_PROMPT_DIR 环境变量
        > 项目默认 prompts/ 目录。
        """

        if directory is not None:
            resolved = Path(directory)
        else:
            env_dir = os.getenv(PROMPT_DIR_ENV, "").strip()
            resolved = (
                Path(env_dir) if env_dir else PROJECT_PROMPT_DIR
            )

        self.directory = resolved

    def get(self, name: str) -> str:
        """加载指定场景的提示词内容。

        每次从磁盘读取（不做跨实例缓存），保证提示词文件
        修改后下一次构建 Agent 即可生效。
        """

        if name not in PROMPT_NAMES:
            raise ValueError(
                f"未知提示词场景：{name!r}，"
                f"必须是 {PROMPT_NAMES} 之一"
            )

        path = self.directory / f"{name}.md"

        if not path.is_file():
            raise PromptNotFoundError(
                f"提示词文件不存在：{path}"
            )

        content = path.read_text(encoding="utf-8").strip()

        if not content:
            raise PromptNotFoundError(
                f"提示词文件内容为空：{path}"
            )

        return content


def load_prompt(
    name: str,
    directory: str | Path | None = None,
) -> str:
    """从默认目录（或指定目录）加载提示词内容。"""

    return PromptManager(directory).get(name)
