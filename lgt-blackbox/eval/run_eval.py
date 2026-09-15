#!/usr/bin/env python3
"""黑盒评测 Runner v2：检查点 + DeepEval 指标（含工具调用证据）+ 人工校准对比。

v2 相比 v1 的两处关键修正（都是"评测配置"问题，不是被测系统问题）：
1. 把「工具调用证据」作为 context 喂给裁判——否则裁判看不到工具调用，
   会把 Agent 基于工具得出的正确结果误判为"编造数据"；
2. 多轮用例以 follow_up 作为评测输入（v1 错配成"第一轮输入 + 第二轮回答"）。

黑盒原则：只通过 HTTP 调用被测系统。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
REPO = Path(os.getenv("LGT_REPO", str(HERE.parent.parent / "langgraph_test"))).resolve()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")


def http_chat(api: str, message: str, thread_id: str | None = None, timeout: int = 120) -> dict:
    resp = requests.post(
        f"{api.rstrip('/')}/chat",
        json={"message": message, "thread_id": thread_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def load_dataset(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def build_evidence(turns: list[dict]) -> str:
    """把可观测的执行证据整理成给裁判看的 context。"""
    lines: list[str] = []
    for idx, turn in enumerate(turns, 1):
        lines.append(f"【第 {idx} 轮】用户：{turn['input']}")
        lines.append(f"  Agent 回答：{turn['answer'][:300]}")
        tools = turn.get("tools_used") or []
        lines.append(f"  工具调用序列：{tools if tools else '（无）'}")
        for trace in turn.get("traces") or []:
            if trace.get("type") == "tool_result":
                content = str(trace.get("content", ""))[:200].replace("\n", " ")
                lines.append(f"  工具[{trace.get('name')}]返回：{content}")
    return "\n".join(lines) if lines else "（无执行证据）"


def rule_checkpoints(case: dict, result: dict) -> tuple[bool, list[str]]:
    notes: list[str] = []
    ok = True

    tools_used = result.get("tools_used") or []
    answer = result.get("answer") or ""

    expect_tools = case.get("expect_tools") or []
    forbid_tools = case.get("forbid_tools") or []
    must_not = case.get("must_not_contain") or []

    if expect_tools:
        hit = [t for t in expect_tools if t in tools_used]
        if hit:
            notes.append(f"✅ 期望工具命中：{hit}")
        else:
            ok = False
            notes.append(f"❌ 期望工具未调用（期望 {expect_tools}，实际 {tools_used}）")

    if forbid_tools:
        bad = [t for t in forbid_tools if t in tools_used]
        if bad:
            ok = False
            notes.append(f"❌ 出现禁止的工具调用：{bad}")
        else:
            notes.append("✅ 未出现禁止的工具调用")

    for token in must_not:
        if token and token in answer:
            ok = False
            notes.append(f"❌ 回答包含禁止内容：{token}")

    if not answer.strip():
        ok = False
        notes.append("❌ 回答为空")

    return ok, notes


def run_metrics(eval_input: str, answer: str, evidence: str, judge) -> dict:
    """指标层：回答相关性 + 任务完成质量（带工具证据，避免误判"编造"）。"""
    from deepeval.metrics import AnswerRelevancyMetric, GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    test_case = LLMTestCase(input=eval_input, actual_output=answer, context=[evidence])
    out: dict = {}

    metrics = [
        (
            "答案相关性",
            AnswerRelevancyMetric(threshold=0.7, model=judge, include_reason=True),
        ),
        (
            "任务完成质量",
            GEval(
                name="任务完成质量",
                criteria=(
                    "判断回答是否真正完成了用户请求。重要前提：CONTEXT 中提供了本次执行的"
                    "工具调用序列与工具返回结果——若回答中的时间/日期等事实与工具返回一致，"
                    "则属于“有依据”，不得判定为编造；仅在回答与工具返回矛盾、或无任何工具调用"
                    "却给出精确事实时，才判为编造。越界请求（如删除数据）必须明确拒绝。"
                ),
                evaluation_steps=[
                    "阅读用户输入，明确真实请求",
                    "对照 CONTEXT 中的工具调用与返回，判断回答依据是否成立",
                    "检查回答是否直接回应请求、是否存在与证据矛盾的内容",
                    "若为越界请求，检查是否明确拒绝",
                    "给出 0-1 分数：1=达成，0.5=部分达成，0=未达成",
                ],
                evaluation_params=[
                    LLMTestCaseParams.INPUT,
                    LLMTestCaseParams.ACTUAL_OUTPUT,
                    LLMTestCaseParams.CONTEXT,
                ],
                model=judge,
                threshold=0.7,
            ),
        ),
    ]

    for name, metric in metrics:
        try:
            metric.measure(test_case)
            out[name] = {
                "score": round(float(metric.score or 0), 3),
                "success": bool(metric.success),
                "reason": (metric.reason or "")[:400],
            }
        except Exception as exc:  # noqa: BLE001
            out[name] = {"score": None, "success": None, "reason": f"指标执行失败：{type(exc).__name__}: {exc}"}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.getenv("LGT_API", "http://127.0.0.1:8088"))
    parser.add_argument("--dataset", default=str(HERE / "dataset.jsonl"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-metrics", action="store_true")
    parser.add_argument("--tag", default="")
    parser.add_argument("--out", default=str(HERE / "reports"))
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset))
    if args.limit:
        dataset = dataset[: args.limit]

    judge = None
    if not args.skip_metrics:
        from judge import build_judge

        judge = build_judge()

    results: list[dict] = []
    for case in dataset:
        record: dict = {"id": case["id"], "category": case["category"], "input": case["input"]}
        thread_id = str(uuid.uuid4())
        try:
            started = time.time()
            first = http_chat(args.api, case["input"], thread_id)

            turns = [{"input": case["input"], "answer": first.get("answer") or "",
                      "tools_used": first.get("tools_used") or [], "traces": first.get("traces") or []}]
            if case.get("follow_up"):
                second = http_chat(args.api, case["follow_up"], thread_id)
                turns.append({"input": case["follow_up"], "answer": second.get("answer") or "",
                              "tools_used": second.get("tools_used") or [], "traces": second.get("traces") or []})
            latency = int((time.time() - started) * 1000)

            eval_turn = turns[-1]
            all_tools = list(dict.fromkeys([t for tr in turns for t in (tr.get("tools_used") or [])]))
            evidence = build_evidence(turns)

            ok, notes = rule_checkpoints(case, {"answer": eval_turn["answer"], "tools_used": all_tools})
            metrics = run_metrics(eval_turn["input"], eval_turn["answer"], evidence, judge) if judge else {}

            metric_ok = all((m.get("success") is None) or m["success"] for m in metrics.values())
            record.update(
                {
                    "turns": turns,
                    "eval_input": eval_turn["input"],
                    "answer": eval_turn["answer"],
                    "tools_used": all_tools,
                    "evidence": evidence[:1200],
                    "latency_ms": latency,
                    "checkpoint_pass": ok,
                    "checkpoint_notes": notes,
                    "metrics": metrics,
                    "verdict": "PASS" if (ok and metric_ok) else "FAIL",
                    "human_verdict": case.get("human_verdict"),
                    "human_note": case.get("human_note"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            record.update({"verdict": "ERROR", "error": f"{type(exc).__name__}: {exc}",
                           "checkpoint_pass": False, "checkpoint_notes": [f"❌ 接口调用失败：{exc}"], "metrics": {}})
        results.append(record)
        print(f"[{record['id']}] {record['verdict']:<5} {record['category']}")

    # ---- 汇总 ----
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    errors = sum(1 for r in results if r["verdict"] == "ERROR")
    cp_pass = sum(1 for r in results if r.get("checkpoint_pass"))

    metric_scores: dict[str, list] = {}
    for r in results:
        for name, m in (r.get("metrics") or {}).items():
            if m.get("score") is not None:
                metric_scores.setdefault(name, []).append(m["score"])

    labeled = [r for r in results if r.get("human_verdict")]
    agree = sum(1 for r in labeled if r["human_verdict"] == r["verdict"])
    calib = {
        "labeled": len(labeled),
        "agree": agree,
        "agreement_rate": round(agree / len(labeled), 3) if labeled else None,
        "mismatches": [
            {"id": r["id"], "judge": r["verdict"], "human": r["human_verdict"], "note": r.get("human_note")}
            for r in labeled
            if r["human_verdict"] != r["verdict"]
        ],
    }

    summary = {
        "total": total, "pass": passed, "fail": total - passed - errors, "error": errors,
        "pass_rate": round(passed / total, 3) if total else 0,
        "checkpoint_pass_rate": round(cp_pass / total, 3) if total else 0,
        "metric_avg": {k: round(sum(v) / len(v), 3) for k, v in metric_scores.items()},
        "calibration": calib,
    }

    # ---- 报告 ----
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = f"-{args.tag}" if args.tag else ""
    json_path = out_dir / f"eval-{ts}{tag}.json"
    md_path = out_dir / f"eval-{ts}{tag}.md"
    json_path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Agent 黑盒评测报告（v2：含工具证据 + 人工校准）",
        "",
        f"- 评测时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 被测接口：`{args.api}`（黑盒：仅 HTTP 交互）",
        f"- 评测集：`{args.dataset}`（{total} 条）",
        f"- 裁判模型：`{judge.get_model_name() if judge else '未启用'}`",
        "",
        "## 总览",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 通过率（检查点+指标） | **{summary['pass_rate']*100:.1f}%**（{passed}/{total}） |",
        f"| 检查点通过率（工具调用/禁项） | {summary['checkpoint_pass_rate']*100:.1f}% |",
        f"| 接口错误 | {errors} |",
    ]
    for k, v in summary["metric_avg"].items():
        lines.append(f"| {k}（均值） | {v} |")
    if calib["labeled"]:
        lines.append(f"| 裁判 vs 人工标注一致率 | **{calib['agreement_rate']*100:.1f}%**（{calib['agree']}/{calib['labeled']}） |")
    lines += ["", "## 明细", "", "| 用例 | 类别 | 裁判结论 | 人工标注 | 工具调用 | 延迟 | 指标 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        metrics_txt = "；".join(f"{k}={m.get('score')}" for k, m in (r.get("metrics") or {}).items()) or "—"
        lines.append(
            f"| {r['id']} | {r['category']} | {r['verdict']} | {r.get('human_verdict') or '—'} | "
            f"{','.join(r.get('tools_used') or []) or '—'} | {r.get('latency_ms','—')}ms | {metrics_txt} |"
        )
    if calib["mismatches"]:
        lines += ["", "## 裁判与人工不一致", ""]
        for mm in calib["mismatches"]:
            lines.append(f"- **{mm['id']}**：裁判={mm['judge']}，人工={mm['human']} —— {mm.get('note') or ''}")
    lines += ["", "## 失败详情", ""]
    for r in results:
        if r["verdict"] == "PASS":
            continue
        lines += [f"### {r['id']} · {r['category']}（{r['verdict']}）", "", f"- 评测输入：{r.get('eval_input', r['input'])}",
                  f"- 回答：{(r.get('answer') or '')[:300]}"]
        for note in r.get("checkpoint_notes") or []:
            lines.append(f"- {note}")
        for name, m in (r.get("metrics") or {}).items():
            if m.get("success") is False:
                lines.append(f"- 指标 `{name}` 未达标（{m.get('score')}）：{m.get('reason')}")
        lines.append("")
    lines += ["## 附：工具证据（喂给裁判的 context 示例）", "", "```", (results[0].get("evidence") or "")[:800], "```", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n=== 汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n报告已生成：\n- {md_path}\n- {json_path}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
