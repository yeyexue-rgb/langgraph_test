"""pytest 会话钩子：评测运行结束自动留档。

- 终端表格由 evals/eval_report.py 在每个用例内直接打印；
- 这里在会话结束时把所有结果写成 reports/eval-<mode>-<时间戳>.json，
  方便入库对比历史趋势（分数回归、架构 A/B）。
"""

from __future__ import annotations

import os

import pytest

from evals.eval_report import REPORTER


@pytest.fixture(scope="session", autouse=True)
def _eval_report_on_session_end():
    yield
    # 没有任何指标/检查项（例如全部 skip）时不产生空报告。
    REPORTER.save(mode=os.getenv("EVAL_AGENT_MODE", "single"))
