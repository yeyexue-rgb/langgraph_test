"""提示词加载器：从 prompts/ 目录读取场景提示词。

设计要点（都是踩过坑总结的）：
1. **目录优先级**：显式传参 > `AGENT_PROMPT_DIR` 环境变量 > 项目默认目录，
   方便切换提示词版本做对照实验；
2. **后缀兼容**：优先 `.md`，兼容 `.txt`——历史上提示词一直是 `.txt`，
   后来允许用 `.md` 写富文本，两种都要能读；
3. **场景白名单**：只允许 `PROMPT_NAMES` 里的场景，
   拼错名字立刻报错，避免"静默拿到空提示词、评测结论全错"这种最坑的故障；
4. **空文件报错**：文件存在但内容为空同样视为错误，不返回空串。

对外 API：
    load_prompt(name, default=None) -> str
    PromptManager(directory=None).get(name) -> str
    PromptNotFoundError / PROMPT_NAMES / PROJECT_PROMPT_DIR
"""

from __future__ import annotations

import os
from pathlib import Path

#: 项目自带提示词目录（默认目录）
PROJECT_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

#: 允许加载的场景白名单
PROMPT_NAMES = (
    "system",
    "supervisor",
    "time_specialist",
    "file_specialist",
    "sql_specialist",
)

#: 文件后缀查找顺序
PROMPT_SUFFIXES = (".md", ".txt")

#: 兜底默认值（仅在文件缺失且未显式传 default 时使用）
_DEFAULTS = {
    "system": "你是一个乐于助人的智能体助手，请用简体中文简洁准确地回答。",
}


class PromptNotFoundError(Exception):
    """提示词文件缺失，或文件内容为空。"""


class PromptManager:
    """按场景加载提示词。

    directory 为空时依次取 AGENT_PROMPT_DIR 环境变量、项目默认目录；
    显式传入的 directory 优先级最高（测试注入隔离目录时用）。
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        if directory is not None:
            self.directory = Path(directory)
        else:
            env_dir = (os.getenv("AGENT_PROMPT_DIR") or "").strip()
            self.directory = Path(env_dir) if env_dir else PROJECT_PROMPT_DIR

    def get(self, name: str) -> str:
        """加载指定场景提示词（已 strip）。"""

        if name not in PROMPT_NAMES:
            raise ValueError(
                f"未知提示词场景：{name!r}，可选值：{list(PROMPT_NAMES)}"
            )

        for suffix in PROMPT_SUFFIXES:
            path = self.directory / f"{name}{suffix}"

            if not path.exists():
                continue

            content = path.read_text(encoding="utf-8").strip()

            if not content:
                raise PromptNotFoundError(f"提示词文件内容为空：{path}")

            return content

        suffixes = "/".join(PROMPT_SUFFIXES)
        raise PromptNotFoundError(
            f"未找到提示词文件：{self.directory}/{name}（尝试后缀 {suffixes}）"
        )


def load_prompt(name: str, default: str | None = None) -> str:
    """便捷加载：等价于 PromptManager().get(name)，缺失时可回退默认值。

    - 文件缺失：有 default 用 default，否则用内置兜底（可能为空串）；
    - 场景名非法：仍然抛 ValueError（拼错名字必须立刻暴露）。
    """

    try:
        return PromptManager().get(name)
    except PromptNotFoundError:
        if default is not None:
            return default

        return _DEFAULTS.get(name, "")
