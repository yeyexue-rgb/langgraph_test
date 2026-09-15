# langgraph_test 黑盒评测实战（DeepEval）

> 目标：**以黑盒方式**评测 `langgraph_test` 项目——评测代码只通过 HTTP 接口与系统交互，不读取、不 import 被测项目的内部实现。
> 工具链：FastAPI 接口适配器 + 规则检查点（确定性）+ DeepEval 指标（LLM-as-judge）。

---

## 1. 目录结构

```
lgt-blackbox/
├── api_server.py          # 接口层：把项目的 AgentService 暴露为 POST /chat（被测系统的"接口"）
├── eval/
│   ├── dataset.jsonl      # 黑盒评测集（8 条：时间能力 / 模糊表达 / 安全边界 / 多轮）
│   ├── run_eval.py        # 评测 Runner：检查点 + 指标 → Markdown/JSON 报告
│   ├── test_blackbox.py   # pytest 版（可进 CI；默认只跑检查点，零成本）
│   ├── judge.py           # DeepEval 裁判模型封装（DashScope 兼容端点上的 Qwen）
│   └── reports/           # 评测报告输出目录
├── sandbox_files/         # 文件检索工具的沙箱根目录（只读样例数据）
└── run_all.sh             # 一键：起服务 → 等健康 → 评测 → 停服务
```

## 2. 黑盒原则（为什么这么设计）

| 关注点 | 做法 |
|---|---|
| 交互方式 | 评测代码**只**调用 `POST /chat`，不 import 项目模块 |
| 接口契约 | 请求 `{message, thread_id?, user_id?, tenant_id?}`；响应 `{status, answer, tools_used, traces, thread_id, latency_ms}` |
| 观测边界 | 只看"能观测到的东西"：回答内容、工具调用序列、延迟、错误 |
| 换系统成本 | 改 `LGT_API` 即可指向任何实现同一契约的服务 |

> 对应系列文章的观点：**黑盒不是限制，是常态**——接口就是契约，过程用 `tools_used`/`traces` 观测；拿不到轨迹时，先推动对方暴露。

## 3. 运行

```bash
# 0) 依赖（假设已在仓库同级准备好 venv）
python -m venv ../.venv-lgt && ../.venv-lgt/bin/pip install -r requirements-eval.txt

# 1) 起被测服务（真实模型：读取 ../langgraph_test/.env 的 DASHSCOPE_API_KEY）
export LGT_FILE_ROOT=$PWD/sandbox_files
../.venv-lgt/bin/uvicorn api_server:app --host 127.0.0.1 --port 8088

# 2) 健康检查
curl -s http://127.0.0.1:8088/health | python -m json.tool

# 3) 跑评测（全部）
../.venv-lgt/bin/python eval/run_eval.py --api http://127.0.0.1:8088

# 常用选项
#   --limit 3        只跑前 3 条（省模型额度）
#   --skip-metrics   只跑检查点（零裁判成本）
#   --tag smoke      报告文件名加标签

# 4) pytest 版（CI 友好）
LGT_API=http://127.0.0.1:8088 ../.venv-lgt/bin/pytest -q eval/test_blackbox.py
```

**无模型环境**：`LGT_MOCK=1 uvicorn api_server:app --port 8088` 可返回固定响应，用于端到端演示与流水线自测。

## 4. 评测设计（两层）

1. **检查点（确定性，零成本）**
   - `expect_tools`：期望调用的工具（如 `parse_natural_datetime`）
   - `forbid_tools`：禁止调用的工具（如危险操作）
   - `must_not_contain`：回答中禁止出现的内容（如"已删除"）
2. **DeepEval 指标（LLM-as-judge）**
   - `AnswerRelevancyMetric`：回答是否切题
   - `GEval("任务完成质量")`：是否真正完成请求 / 是否编造 / 越界是否拒绝
   - 阈值默认 0.7；结论 = 检查点通过 **且** 指标达标

## 5. 已知局限（写清楚，才叫专业）

- 本仓库上游**缺少部分模块**（`hitl.py`、`sql_provider.py`、`prompts/` 等），本目录用最小"补桥实现"让 `AgentService` 可运行；评测对象是"该项目的单 Agent 模式（single）"；
- 裁判模型与被测模型同为 Qwen（自评偏差），生产应换独立裁判并做人工标注校准；
- 工具调用信息来自接口返回的 `tools_used`（黑盒观测项）；若服务不返回该字段，只能退化为"仅输出侧断言"；
- 评测集仅 8 条，属"最小可用集"，需按线上真实流量持续扩充（第一/二季方法论）。
