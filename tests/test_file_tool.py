"""文件工具单元测试：验证查询能力与路径越界防护。

不依赖大模型，直接调用 Tool，断言 JSON 返回结果。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from providers.file_provider import FileToolProvider


@pytest.fixture
def provider(tmp_path: Path) -> FileToolProvider:
    (tmp_path / "报告").mkdir()
    (tmp_path / "代码").mkdir()

    (tmp_path / "测试计划.txt").write_text(
        "测试计划",
        encoding="utf-8",
    )
    (tmp_path / "报告" / "回归报告.pdf").write_bytes(
        b"fake-pdf"
    )
    (tmp_path / "代码" / "test_login.py").write_text(
        "def test_login(): pass",
        encoding="utf-8",
    )

    return FileToolProvider(root_directory=tmp_path)


def invoke_tool(
    provider: FileToolProvider,
    arguments: dict,
) -> dict:
    tool = provider.get_tools()[0]
    return json.loads(tool.invoke(arguments))


def test_list_all_files(
    provider: FileToolProvider,
) -> None:
    result = invoke_tool(
        provider,
        {
            "relative_directory": ".",
            "recursive": True,
        },
    )

    assert result["status"] == "success"
    assert result["count"] == 3


def test_search_by_extension(
    provider: FileToolProvider,
) -> None:
    result = invoke_tool(
        provider,
        {
            "extensions": [".py"],
            "recursive": True,
        },
    )

    assert result["count"] == 1
    assert result["files"][0]["name"] == "test_login.py"


def test_search_by_keyword(
    provider: FileToolProvider,
) -> None:
    result = invoke_tool(
        provider,
        {
            "keyword": "回归",
            "recursive": True,
        },
    )

    assert result["count"] == 1
    assert result["files"][0]["name"] == "回归报告.pdf"


def test_search_in_subdirectory(
    provider: FileToolProvider,
) -> None:
    result = invoke_tool(
        provider,
        {
            "relative_directory": "代码",
            "recursive": False,
        },
    )

    assert result["count"] == 1
    assert (
        result["files"][0]["relative_path"]
        == str(Path("代码") / "test_login.py")
    )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "..",
        "../其他目录",
        r"..\其他目录",
        r"C:\Windows",
        r"D:\其他目录",
    ],
)
def test_reject_path_escape(
    provider: FileToolProvider,
    unsafe_path: str,
) -> None:
    result = invoke_tool(
        provider,
        {
            "relative_directory": unsafe_path,
        },
    )

    assert result["status"] == "access_denied"


def test_tool_does_not_expose_write_operations(
    provider: FileToolProvider,
) -> None:
    tool = provider.get_tools()[0]
    schema = tool.args_schema.model_json_schema()
    properties = schema["properties"]

    assert "content" not in properties
    assert "delete" not in properties
    assert "destination" not in properties
