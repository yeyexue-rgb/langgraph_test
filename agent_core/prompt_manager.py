"""（补桥实现）提示词加载器：从 prompts/ 目录读取，缺失时回退默认值。

说明：上游仓库未包含本模块，此处为黑盒评测环境提供最小实现，
行为契约：load_prompt(name) -> str。
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_DIR = Path(os.getenv("AGENT_PROMPT_DIR", str(_REPO_ROOT / "prompts")))

_DEFAULTS = {
    "system": "你是一个乐于助人的智能体助手，请用简体中文简洁准确地回答。",
}


def load_prompt(name: str, default: str | None = None) -> str:
    """按名称加载提示词（prompts/<name>.txt）。"""
    path = _PROMPT_DIR / f"{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    if default is not None:
        return default
    return _DEFAULTS.get(name, "")
