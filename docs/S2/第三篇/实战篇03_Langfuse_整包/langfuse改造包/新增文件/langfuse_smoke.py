#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Langfuse 接入冒烟脚本：跑一轮真实对话，把轨迹推到 Langfuse。

用法（项目根目录，先激活虚拟环境）：

    # 1) 只在本地跑通、不追踪（未配 LANGFUSE_* 时自动是这个状态）
    python scripts/langfuse_smoke.py

    # 2) 追踪到 Langfuse 云 / 自托管
    export LANGFUSE_PUBLIC_KEY=pk-lf-...
    export LANGFUSE_SECRET_KEY=sk-lf-...
    export LANGFUSE_HOST=https://cloud.langfuse.com     # 自托管改成自己的地址
    python scripts/langfuse_smoke.py "当前一共有多少条 P0 优先级的测试用例？"

脚本会打印：追踪开关状态、本轮回答、工具轨迹、耗时，
并在结束时 flush，确保数据真正落到平台。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from agent_core.observability import (  # noqa: E402
    build_langfuse_handler,
    flush,
    langfuse_enabled,
    sample_rate,
)
from evals.agent_provider import invoke_agent  # noqa: E402


DEFAULT_QUERY = "当前一共有多少条 P0 优先级的测试用例？"


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    agent_mode = os.getenv("AGENT_MODE", "single").strip() or "single"

    enabled = langfuse_enabled()
    handler = build_langfuse_handler()

    print("=" * 62)
    print(f"追踪开关     : {'开' if enabled else '关（未配置 LANGFUSE_*，零影响）'}")
    print(f"采样比例     : {sample_rate()}")
    print(f"回调处理器   : {'就绪' if handler is not None else '未创建（no-op）'}")
    print(f"被测架构     : {agent_mode}")
    print("=" * 62)

    started = time.time()
    result = invoke_agent(query, agent_mode=agent_mode)
    elapsed = (time.time() - started) * 1000

    print(f"问题         : {query}")
    print(f"状态         : {result.get('status')}")
    print(f"回答         : {str(result.get('answer'))[:120]}")
    print(f"工具轨迹     : {result.get('tools_used')}")
    print(f"本轮耗时     : {elapsed:.0f} ms")

    flush()

    if enabled:
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        print(f"\n已 flush。到 {host} 查看 Trace（按 session 检索本轮 thread_id）。")
    else:
        print("\n未启用追踪：配置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 后重跑。")


if __name__ == "__main__":
    main()
