"""提示词轻量外置管理测试。

不依赖模型，每次提交都跑：
1. 默认目录下五个场景提示词完整可加载；
2. 自定义目录注入（测试场景隔离）；
3. 未知场景、缺失文件、空文件均有明确报错；
4. AGENT_PROMPT_DIR 环境变量覆盖默认目录。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.prompt_manager import (
    PROMPT_NAMES,
    PROJECT_PROMPT_DIR,
    PromptManager,
    PromptNotFoundError,
    load_prompt,
)


# ============================================================================
# 默认目录：项目自带提示词必须完整可用
# ============================================================================

class TestDefaultPromptDirectory:

    @pytest.mark.parametrize("name", PROMPT_NAMES)
    def test_all_default_prompts_loadable(self, name: str) -> None:
        content = load_prompt(name)

        assert content
        assert not content.startswith("\n")

    def test_default_directory_is_project_prompts(self) -> None:
        manager = PromptManager()

        assert manager.directory == PROJECT_PROMPT_DIR

    def test_system_prompt_contains_core_rule(self) -> None:
        """关键规则不能在外置迁移中丢失。"""

        content = load_prompt("system")

        assert "AgentResponse" in content
        assert "不得由模型自行计算相对日期" in content

    def test_supervisor_prompt_mentions_all_specialists(
        self,
    ) -> None:
        content = load_prompt("supervisor")

        assert "time_specialist" in content
        assert "file_specialist" in content
        assert "sql_specialist" in content


# ============================================================================
# 自定义目录：测试可注入隔离的提示词
# ============================================================================

class TestCustomPromptDirectory:

    def test_custom_directory_overrides_default(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "system.txt").write_text(
            "自定义测试提示词",
            encoding="utf-8",
        )

        manager = PromptManager(tmp_path)

        assert manager.get("system") == "自定义测试提示词"

    def test_unknown_scene_rejected(self) -> None:
        with pytest.raises(ValueError):
            PromptManager().get("not_a_scene")

    def test_missing_file_raises_clear_error(
        self,
        tmp_path: Path,
    ) -> None:
        manager = PromptManager(tmp_path)

        with pytest.raises(PromptNotFoundError):
            manager.get("system")

    def test_empty_file_raises_clear_error(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "system.txt").write_text(
            "   \n  ",
            encoding="utf-8",
        )

        with pytest.raises(PromptNotFoundError):
            PromptManager(tmp_path).get("system")

    def test_content_stripped_on_load(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "system.txt").write_text(
            "\n\n  提示词正文  \n",
            encoding="utf-8",
        )

        assert (
            PromptManager(tmp_path).get("system")
            == "提示词正文"
        )


# ============================================================================
# 环境变量覆盖：便于切换提示词版本做对照实验
# ============================================================================

class TestPromptDirectoryEnvOverride:

    def test_env_overrides_default_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "system.txt").write_text(
            "环境变量版提示词",
            encoding="utf-8",
        )

        monkeypatch.setenv("AGENT_PROMPT_DIR", str(tmp_path))

        assert load_prompt("system") == "环境变量版提示词"

    def test_explicit_directory_wins_over_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_dir = tmp_path / "env"
        explicit_dir = tmp_path / "explicit"
        env_dir.mkdir()
        explicit_dir.mkdir()

        (env_dir / "system.txt").write_text(
            "环境变量版",
            encoding="utf-8",
        )
        (explicit_dir / "system.txt").write_text(
            "显式目录版",
            encoding="utf-8",
        )

        monkeypatch.setenv("AGENT_PROMPT_DIR", str(env_dir))

        manager = PromptManager(explicit_dir)

        assert manager.get("system") == "显式目录版"
