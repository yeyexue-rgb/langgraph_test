"""个人空间文件查找的 LangChain Tool 与 Provider。

安全约束：
- 只能查询 D:\\个人空间 下的文件元信息；
- 只读，不提供读取、修改、删除能力；
- 阻止 ..、绝对路径与符号链接越界。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from langchain_core.tools import BaseTool
from langchain.tools import tool
from pydantic import BaseModel, Field


DEFAULT_PERSONAL_SPACE = Path(r"D:\个人空间")


class FileSearchInput(BaseModel):
    """Agent 可见的文件查询参数。"""

    keyword: str | None = Field(
        default=None,
        max_length=100,
        description="文件名关键词，不填写表示不限制文件名",
    )

    extensions: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "文件扩展名列表，例如 ['.py', '.txt']；"
            "不填写表示不限制扩展名"
        ),
    )

    relative_directory: str = Field(
        default=".",
        max_length=200,
        description=(
            "相对于 D:\\个人空间 的子目录。"
            "禁止传入绝对路径和 .."
        ),
    )

    recursive: bool = Field(
        default=True,
        description="是否递归查找子目录",
    )

    modified_after: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "只返回该时间之后修改的文件，"
            "必须使用带时区的 ISO 8601 时间"
        ),
    )

    modified_before: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "只返回该时间之前修改的文件，"
            "必须使用带时区的 ISO 8601 时间"
        ),
    )

    max_results: int = Field(
        default=50,
        ge=1,
        le=200,
        description="最多返回的文件数量",
    )


class FileAccessDenied(ValueError):
    """请求路径超出允许访问的目录。"""


class FileSearchService:
    """只能查询指定根目录的只读文件服务。"""

    def __init__(
        self,
        root_directory: str | Path = DEFAULT_PERSONAL_SPACE,
    ) -> None:
        self.root_directory = Path(
            root_directory
        ).expanduser().resolve(strict=False)

    def _validate_root(self) -> None:
        if not self.root_directory.exists():
            raise FileNotFoundError(
                f"目录不存在：{self.root_directory}"
            )

        if not self.root_directory.is_dir():
            raise NotADirectoryError(
                f"不是文件夹：{self.root_directory}"
            )

    def _safe_directory(
        self,
        relative_directory: str,
    ) -> Path:
        """解析并检查目录，防止路径穿越。"""

        self._validate_root()

        raw_value = relative_directory.strip() or "."

        windows_path = PureWindowsPath(raw_value)
        local_path = Path(raw_value)

        if windows_path.is_absolute() or local_path.is_absolute():
            raise FileAccessDenied("禁止访问绝对路径")

        if ".." in windows_path.parts or ".." in local_path.parts:
            raise FileAccessDenied("禁止使用 .. 访问上级目录")

        target = (
            self.root_directory / local_path
        ).resolve(strict=True)

        try:
            target.relative_to(self.root_directory)
        except ValueError as exc:
            raise FileAccessDenied(
                "目标目录超出个人空间"
            ) from exc

        if not target.is_dir():
            raise NotADirectoryError(
                f"目标不是文件夹：{relative_directory}"
            )

        return target

    @staticmethod
    def _parse_filter_time(
        value: str | None,
        field_name: str,
    ) -> datetime | None:
        if value is None:
            return None

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"{field_name} 必须是 ISO 8601 时间"
            ) from exc

        if parsed.tzinfo is None:
            raise ValueError(
                f"{field_name} 必须包含时区"
            )

        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _normalize_extensions(
        extensions: list[str],
    ) -> set[str]:
        normalized: set[str] = set()

        for extension in extensions:
            value = extension.strip().lower()

            if not value:
                continue

            if not value.startswith("."):
                value = f".{value}"

            normalized.add(value)

        return normalized

    def search(
        self,
        *,
        keyword: str | None = None,
        extensions: list[str] | None = None,
        relative_directory: str = ".",
        recursive: bool = True,
        modified_after: str | None = None,
        modified_before: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """查询文件，不读取文件内容。"""

        target = self._safe_directory(relative_directory)

        normalized_keyword = (
            keyword.strip().lower()
            if keyword and keyword.strip()
            else None
        )
        normalized_extensions = self._normalize_extensions(
            extensions or []
        )

        after_time = self._parse_filter_time(
            modified_after,
            "modified_after",
        )
        before_time = self._parse_filter_time(
            modified_before,
            "modified_before",
        )

        if (
            after_time is not None
            and before_time is not None
            and after_time > before_time
        ):
            raise ValueError(
                "modified_after 不能晚于 modified_before"
            )

        iterator = (
            target.rglob("*")
            if recursive
            else target.iterdir()
        )

        results: list[dict[str, Any]] = []
        skipped_count = 0

        for candidate in iterator:
            if len(results) >= max_results:
                break

            try:
                # resolve() 可以识别指向根目录外部的符号链接。
                resolved_candidate = candidate.resolve(strict=True)
                resolved_candidate.relative_to(self.root_directory)

                if not resolved_candidate.is_file():
                    continue

                if (
                    normalized_keyword
                    and normalized_keyword
                    not in resolved_candidate.name.lower()
                ):
                    continue

                if (
                    normalized_extensions
                    and resolved_candidate.suffix.lower()
                    not in normalized_extensions
                ):
                    continue

                stat_result = resolved_candidate.stat()
                modified_utc = datetime.fromtimestamp(
                    stat_result.st_mtime,
                    tz=timezone.utc,
                )

                if after_time and modified_utc <= after_time:
                    continue

                if before_time and modified_utc >= before_time:
                    continue

                relative_path = resolved_candidate.relative_to(
                    self.root_directory
                )

                results.append(
                    {
                        "name": resolved_candidate.name,
                        "relative_path": str(relative_path),
                        "extension": (
                            resolved_candidate.suffix.lower()
                        ),
                        "size_bytes": stat_result.st_size,
                        "modified_at": (
                            modified_utc.isoformat()
                        ),
                    }
                )

            except (
                FileNotFoundError,
                PermissionError,
                OSError,
                ValueError,
            ):
                skipped_count += 1

        results.sort(
            key=lambda item: item["relative_path"].lower()
        )

        return {
            "status": "success",
            "scope": str(self.root_directory),
            "relative_directory": relative_directory,
            "count": len(results),
            "truncated": len(results) >= max_results,
            "skipped_count": skipped_count,
            "files": results,
        }


def create_file_search_tool(
    service: FileSearchService,
) -> BaseTool:
    """根据文件服务创建 LangChain Tool。"""

    @tool(
        "search_personal_space_files",
        args_schema=FileSearchInput,
    )
    def search_personal_space_files(
        keyword: str | None = None,
        extensions: list[str] | None = None,
        relative_directory: str = ".",
        recursive: bool = True,
        modified_after: str | None = None,
        modified_before: str | None = None,
        max_results: int = 50,
    ) -> str:
        """查找 D 盘"个人空间"文件夹内的文件。

        可以按文件名、扩展名、子目录和修改时间过滤。
        该工具只能查询文件信息，不能读取、修改或删除文件。
        """

        try:
            result = service.search(
                keyword=keyword,
                extensions=extensions,
                relative_directory=relative_directory,
                recursive=recursive,
                modified_after=modified_after,
                modified_before=modified_before,
                max_results=max_results,
            )

        except FileAccessDenied as exc:
            result = {
                "status": "access_denied",
                "message": str(exc),
            }

        except (
            FileNotFoundError,
            NotADirectoryError,
            ValueError,
        ) as exc:
            result = {
                "status": "error",
                "error_code": "INVALID_FILE_QUERY",
                "message": str(exc),
            }

        except Exception as exc:
            result = {
                "status": "error",
                "error_code": "INTERNAL_ERROR",
                "message": f"文件查询失败：{exc}",
            }

        return json.dumps(result, ensure_ascii=False)

    return search_personal_space_files


class FileToolProvider:
    """个人空间文件工具提供者。"""

    def __init__(
        self,
        root_directory: str | Path = DEFAULT_PERSONAL_SPACE,
    ) -> None:
        self.service = FileSearchService(root_directory)
        self.tool = create_file_search_tool(self.service)

    @property
    def name(self) -> str:
        return "personal_space_files"

    def get_tools(self) -> list[Any]:
        return [self.tool]

    def health_check(self) -> dict[str, Any]:
        root = self.service.root_directory

        if not root.exists():
            return {
                "status": "unhealthy",
                "tool_count": 1,
                "message": f"目录不存在：{root}",
            }

        if not root.is_dir():
            return {
                "status": "unhealthy",
                "tool_count": 1,
                "message": f"路径不是文件夹：{root}",
            }

        return {
            "status": "healthy",
            "tool_count": 1,
            "scope": str(root),
            "mode": "read_only",
        }
