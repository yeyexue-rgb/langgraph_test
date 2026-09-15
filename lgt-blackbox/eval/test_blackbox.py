"""黑盒评测（pytest 版）：检查点断言，默认不调用裁判模型（快、零成本）。

用法：
  pytest -q test_blackbox.py                     # 仅检查点
  RUN_METRICS=1 pytest -q test_blackbox.py       # 附加 DeepEval 指标
  LGT_API=http://host:port pytest -q test_blackbox.py
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
import requests

HERE = Path(__file__).resolve().parent
API = os.getenv("LGT_API", "http://127.0.0.1:8088")
RUN_METRICS = os.getenv("RUN_METRICS", "0") == "1"


def _load_cases():
    cases = []
    for line in (HERE / "dataset.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


CASES = _load_cases()


def _chat(message: str, thread_id: str | None = None) -> dict:
    resp = requests.post(f"{API}/chat", json={"message": message, "thread_id": thread_id}, timeout=120)
    resp.raise_for_status()
    return resp.json()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_blackbox_case(case: dict) -> None:
    thread_id = str(uuid.uuid4())
    first = _chat(case["input"], thread_id)
    answer = first.get("answer") or ""
    tools_used = first.get("tools_used") or []

    if case.get("follow_up"):
        second = _chat(case["follow_up"], thread_id)
        answer = second.get("answer") or ""
        tools_used = list(dict.fromkeys(tools_used + (second.get("tools_used") or [])))

    assert answer.strip(), "回答不能为空"

    for tool in case.get("expect_tools") or []:
        assert tool in tools_used, f"期望调用 {tool}，实际 {tools_used}"

    for tool in case.get("forbid_tools") or []:
        assert tool not in tools_used, f"不该调用 {tool}，实际 {tools_used}"

    for token in case.get("must_not_contain") or []:
        assert token not in answer, f"回答不应包含「{token}」"

    if RUN_METRICS:
        from judge import build_judge
        from run_eval import run_metrics

        metrics = run_metrics(case, answer, build_judge())
        for name, m in metrics.items():
            if m.get("success") is False:
                pytest.fail(f"指标 {name} 未达标：{m.get('score')} - {m.get('reason')}")
