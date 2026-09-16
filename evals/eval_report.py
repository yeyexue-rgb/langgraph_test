"""评测结果留档：终端汇总表 + JSON 归档（每次运行自动落盘）。

为什么需要它：
- DeepEval 的 `assert_test` 只吐"通过/失败"，**不打印 metric.score / metric.reason**，
  评测跑完等于一个黑盒——裁判给 0.7 还是 0.95、为什么扣分，看不到；
- 本模块把指标逐个 measure 一次，记录 score / threshold / 是否通过 / 裁判理由，
  再统一断言（失败信息里直接带裁判理由），并在会话结束时写成
  `reports/eval-<mode>-<时间戳>.json`，可入库对比历史趋势。

用法（用例里）：
    from evals.eval_report import REPORTER
    REPORTER.measure_and_record("SQL · P0 用例数量", case, [m1, m2], extra={...})
    REPORTER.record_case("安全 · 提示注入不得泄露", {"leaked": False})   # 纯规则用例

环境变量：
- EVAL_REPORT_DIR：归档目录（默认 ./reports）
- EVAL_REPORT=0：只打印不落盘（CI 临时跑可用）
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_MAX_REASON = 300


def _force_utf8() -> None:
    """Windows 控制台默认 GBK，中文/符号会 UnicodeEncodeError —— 强制 UTF-8。"""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 —— 非 tty / 不支持时忽略
            pass


def _measure(metric: Any, case: Any) -> None:
    """调用 metric.measure（兼容不同 deepeval 小版本的参数差异）。"""

    try:
        metric.measure(case, _show_indicator=False)
    except TypeError:
        metric.measure(case)


def _is_success(metric: Any) -> bool:
    result = getattr(metric, "is_successful", None)

    if callable(result):
        try:
            return bool(result())
        except Exception:  # noqa: BLE001
            pass

    score, threshold = getattr(metric, "score", None), getattr(metric, "threshold", None)

    if score is None:
        return False

    return bool(score) if threshold is None else float(score) >= float(threshold)


def _num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:.3f}" if isinstance(value, float) else str(value)
    return str(value)


def _clip(text: Any, limit: int = _MAX_REASON) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _pad(text: str, width: int) -> str:
    """按显示宽度补空格（中文按 2 列计），让终端表格对齐。"""

    shown = sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)
    return text + " " * max(1, width - shown)


class EvalReporter:
    """收集本次运行的评测结果，打印终端表格并归档 JSON。"""

    def __init__(self) -> None:
        _force_utf8()
        self.records: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ 记录
    def measure_and_record(
        self,
        case_name: str,
        case: Any,
        metrics: list[Any],
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """逐个 measure 指标 → 记录分数与理由 → 有失败则断言失败。"""

        rows: list[dict[str, Any]] = []

        for metric in metrics:
            _measure(metric, case)
            rows.append(
                {
                    "name": type(metric).__name__,
                    "score": getattr(metric, "score", None),
                    "threshold": getattr(metric, "threshold", None),
                    "success": _is_success(metric),
                    "reason": getattr(metric, "reason", None),
                }
            )

        entry = {"case": case_name, "metrics": rows, "checks": {}, "extra": extra or {}}
        self.records.append(entry)
        self._print_entry(entry)

        failed = [row for row in rows if not row["success"]]

        if failed:
            detail = "; ".join(
                f"{row['name']}={_num(row['score'])}（阈值 {_num(row['threshold'])}）"
                f" 理由：{_clip(row['reason'])}"
                for row in failed
            )

            raise AssertionError(f"[评测未通过] {case_name} → {detail}")

        return entry

    def record_case(
        self,
        case_name: str,
        checks: dict[str, Any],
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """纯规则类用例（无 LLM 裁判）：只记录关键检查项，一并进归档。"""

        entry = {"case": case_name, "metrics": [], "checks": checks, "extra": extra or {}}
        self.records.append(entry)
        self._print_entry(entry)
        return entry

    # ------------------------------------------------------------------ 输出
    def _print_entry(self, entry: dict[str, Any]) -> None:
        print(f"\n[用例] {entry['case']}")
        print("  " + "-" * 96)

        if entry["metrics"]:
            header = (
                _pad("指标", 26)
                + _pad("score", 9)
                + _pad("阈值", 8)
                + _pad("结果", 8)
                + "裁判理由"
            )
            print("  " + header)

            for row in entry["metrics"]:
                print(
                    "  "
                    + _pad(row["name"], 26)
                    + _pad(_num(row["score"]), 9)
                    + _pad(_num(row["threshold"]), 8)
                    + _pad("通过" if row["success"] else "未通过", 8)
                    + _clip(row["reason"])
                )

        if entry["checks"]:
            print("  " + _pad("检查项", 26) + "值")
            for key, value in entry["checks"].items():
                print("  " + _pad(key, 26) + str(value))

        if entry["extra"]:
            print("  " + _pad("上下文", 26) + json.dumps(entry["extra"], ensure_ascii=False))

    def save(self, mode: str = "single", path: str | Path | None = None) -> Path | None:
        """归档本次运行结果；返回写入路径（未落盘时返回 None）。"""

        if not self.records or os.getenv("EVAL_REPORT", "1") == "0":
            return None

        directory = Path(os.getenv("EVAL_REPORT_DIR", "reports"))
        directory.mkdir(parents=True, exist_ok=True)

        target = (
            Path(path)
            if path
            else directory / f"eval-{mode}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        )

        rows = [row for entry in self.records for row in entry["metrics"]]

        payload = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "agent_mode": mode,
            "summary": {
                "cases": len(self.records),
                "metrics_total": len(rows),
                "metrics_passed": sum(1 for row in rows if row["success"]),
                "avg_score": (
                    round(sum(float(r["score"] or 0) for r in rows) / len(rows), 3)
                    if rows
                    else None
                ),
            },
            "records": self.records,
        }

        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = payload["summary"]
        print(
            f"\n[评测汇总] 架构={mode} 用例={summary['cases']} "
            f"指标通过={summary['metrics_passed']}/{summary['metrics_total']} "
            f"平均分={_num(summary['avg_score'])}"
        )
        print(f"[评测留档] {target.resolve()}")

        return target


REPORTER = EvalReporter()
