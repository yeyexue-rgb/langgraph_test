"""DeepEval 自定义裁判模型：LLM-as-judge 走 DashScope（OpenAI 兼容端点）。

为什么不用 DeepEval 默认的 OpenAI：
- 本项目业务模型走 DashScope qwen，不需要额外申请 OpenAI key；
- 裁判模型可通过环境变量 EVAL_JUDGE_MODEL 覆盖（默认与业务模型同源）。

注意（对应文章"坑 1：裁判不校准"）：
- 裁判与被测模型同源会有"自评偏置"，分数容易虚高；
- 正式使用建议 EVAL_JUDGE_MODEL 指定更强的模型，
  并用人工标注集定期校准裁判。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from deepeval.models import DeepEvalBaseLLM
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_core.settings import load_agent_settings  # noqa: E402


class DashScopeJudgeModel(DeepEvalBaseLLM):
    """用 DashScope qwen 充当 DeepEval 的裁判模型。"""

    def __init__(self, model_name: str | None = None) -> None:
        settings = load_agent_settings()

        self.model_name = (
            model_name
            or os.getenv("EVAL_JUDGE_MODEL", "")
            or settings.model_name
        )
        self.model = ChatOpenAI(
            model=self.model_name,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=0,
            streaming=False,
            # 关闭思考模式，保证裁判输出干净的 JSON。
            extra_body={"enable_thinking": False},
        )

    def load_model(self) -> ChatOpenAI:
        return self.model

    def get_model_name(self) -> str:
        return self.model_name

    def generate(
        self,
        prompt: str,
        schema: type | None = None,
    ) -> Any:
        response = self.model.invoke(prompt)
        text = _content_to_text(response.content)

        if schema is None:
            return text

        return _parse_schema(text, schema)

    async def a_generate(
        self,
        prompt: str,
        schema: type | None = None,
    ) -> Any:
        response = await self.model.ainvoke(prompt)
        text = _content_to_text(response.content)

        if schema is None:
            return text

        return _parse_schema(text, schema)


def _content_to_text(content: Any) -> str:
    """把模型输出内容统一转成纯文本。"""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []

        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))

        return "".join(parts)

    return str(content)


def _parse_schema(text: str, schema: type) -> Any:
    """从裁判输出中提取 JSON 并按 schema 实例化（容忍 markdown 代码块包裹）。"""

    match = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(match.group(0)) if match else {}
    return schema(**data)
