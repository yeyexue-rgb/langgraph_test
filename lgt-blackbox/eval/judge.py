"""DeepEval 裁判模型封装：把 DashScope(OpenAI 兼容) 的 Qwen 接成 DeepEval 的 LLM。

为什么需要它：
- DeepEval 的指标（AnswerRelevancy / GEval 等）需要一个"裁判模型"；
- 本项目用的是 DashScope 兼容端点上的 Qwen，不是 OpenAI 官方端点；
- 用 DeepEvalBaseLLM 包一层，评测代码即可完全复用项目自身的模型接入。

注意：用同一个模型既当"被测"又当"裁判"存在自评偏差，
生产实践应换独立裁判模型并做人工校准（详见报告"局限"一节）。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from deepeval.models import DeepEvalBaseLLM


def _extract_json(text: str) -> Any:
    """从模型输出里尽力提取 JSON 对象。"""
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:  # noqa: BLE001
        return None


class DashScopeJudge(DeepEvalBaseLLM):
    """以 DashScope 兼容端点上的 Qwen 作为裁判模型。"""

    def __init__(self) -> None:
        self.model_name = os.getenv("MODEL_NAME", "qwen3.8-max").strip()
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self.base_url = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).strip()
        self.temperature = float(os.getenv("JUDGE_TEMPERATURE", "0"))
        self._client = None

    # --- DeepEval 要求的接口 ---
    def load_model(self):
        from openai import OpenAI

        if not self.api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法初始化裁判模型")
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def get_model_name(self) -> str:
        return f"dashscope:{self.model_name}"

    def generate(self, prompt: str, schema=None) -> Any:
        if self._client is None:
            self.load_model()
        resp = self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            extra_body={"enable_thinking": False},
        )
        text = resp.choices[0].message.content or ""
        if schema is not None:
            data = _extract_json(text)
            if data is not None:
                try:
                    return schema(**data)
                except Exception:  # noqa: BLE001
                    pass
            # 兜底：尝试单字段构造
            try:
                return schema.model_validate({"reason": text[:800]})
            except Exception:  # noqa: BLE001
                return text
        return text

    async def a_generate(self, prompt: str, schema=None) -> Any:
        return self.generate(prompt, schema)


def build_judge() -> DashScopeJudge:
    return DashScopeJudge()
