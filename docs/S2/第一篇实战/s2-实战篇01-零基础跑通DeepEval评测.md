# 零基础跑通第一套 Agent 评测：4 条用例，两种架构

> Agent 测试进阶实战（第二季）· 实战篇 01
> 配套源码：https://github.com/yeyexue-rgb/langgraph_test（完整可运行版本见文末网盘）

---

## 先给你看两张截图

我在自己的 Windows 机器（Python 3.13 + deepeval 4.2.3）上，跑了同一个评测文件两次：

```powershell
(langchain_project) PS D:\python_project\langchain_project> pytest evals/test_agent_eval.py -m integration
evals\test_agent_eval.py ....                                     [100%]
4 passed, 1 warning in 24.85s
```

```powershell
> $env:EVAL_AGENT_MODE="subagents"; pytest evals/test_agent_eval.py -m integration
evals\test_agent_eval.py ....                                     [100%]
4 passed, 1 warning in 32.40s
```

4 条用例、两种架构（单 Agent / Supervisor 多 Agent 分工）全绿。

这篇要证明一件事：**Agent 评测不是玄学，它是一种可以被零基础测试工程师掌握的手艺**。下面我会先立论（评测到底在测什么），再拆开一条用例给你看零件，然后带你把它跑起来，最后把我踩过的坑一个个摊开。看完你就能自己跑出上面这两张截图。

---

## 一、先立论：Agent 评测，测的不是「答案」，是「答案 + 过程」

传统接口测试的判据很干脆：返回对不对。这个判据放到 Agent 上，会漏掉一半的 bug。

论证很简单——**一个 Agent 完全可能给你一个正确结论，但过程是错的**。它没有查数据，而是"猜"对了。

这就是 Agent 评测里最反直觉的一点：

| 情形 | 表面 | 真相 | 后果 |
|---|---|---|---|
| 结论对、过程错 | 测试通过 | 它是猜的，没用工具 | 数据一变就错，你还不知道该改哪 |
| 结论错、过程对 | 测试失败 | 工具调对了，是总结错了 | 问题在提示词，不在数据 |

**所以 Agent 评测必须同时看两样东西：最终输出，和工具调用轨迹。**

这句话是整个评测体系的地基。它直接决定了下面这条原则——

**一条用例，要写两层断言：**

1. **规则层**（确定性、零成本、先跑）：关键事实是否出现、该调的工具调没调、禁止的内容有没有泄露；
2. **指标层**（LLM 裁判、有成本、后跑）：答案相关性、任务完成质量这类"主观维度"。

规则能判死的，绝不用裁判——这是成本控制，也是准确度控制。

---

## 二、解剖一条用例：四个零件

一条能进 CI、能复现的 Agent 评测用例，拆开只有四个零件：

| 零件 | 它在回答什么问题 | 缺了它会怎样 |
|---|---|---|
| **输入** input | 用户会怎么问？ | 用例不可复现 |
| **期望** expected | 什么叫"对"？（ground truth + 该调的工具） | 只能靠裁判"感觉"，没有标准 |
| **证据** evidence | 它到底调了什么工具？（轨迹） | 漏掉"结果对、过程错" |
| **判定** judge | 通过还是失败？依据是什么？ | 结论无凭无据 |

对照代码看最清楚。这是本期的 SQL 用例（可直接抄进你的项目）：

```python
def test_sql_p0_case_count() -> None:
    """SQL 场景：数量类问题（ground truth 来自种子数据 = 3 条）。"""

    query = "当前一共有多少条 P0 优先级的测试用例？"      # ① 输入
    result = invoke(query)

    # ② 规则层：确定性、零成本，先跑
    assert result["status"] == "success"
    assert "3" in result["answer"]                        # ground truth = 3

    # ③ 证据层：把工具调用轨迹交给指标
    case = LLMTestCase(
        input=query,
        actual_output=result["answer"],
        expected_tools=[ToolCall(name="sql_db_query")],                # 期望：该调查库工具
        tools_called=[ToolCall(name=t) for t in result["tools_used"]], # 实际：它调了什么
    )

    # ④ 判定层：过程正确性 + 任务完成度
    assert_test(case, [
        ToolCorrectnessMetric(threshold=0.7, model=JUDGE),   # 过程对不对
        TaskCompletionMetric(threshold=0.7, model=JUDGE),    # 任务完成没
    ])
```

四个零件一目了然。注意第 ③ 步：**`tools_used` 是从被测系统一路带回评测端的**。没有这条证据，`ToolCorrectnessMetric` 无从判断，你也就退回到了"只看输出"的老路。

---

## 三、让用例「可复现」的三件事

写完用例不等于能跑。下面三件事不做，你的评测就是"一次性"的。

**第一件：ground truth 要有出处。**
SQL 用例里的"3"，不是我拍脑袋写的，来自**种子数据**：

```bash
python scripts/seed_test_db.py   # 生成测试管理库：P0 用例 3 条 / blocker 缺陷 2 个
```

用例的期望值必须能从数据里推出来。否则换台机器、换个人跑，结论就不一样。

**第二件：每条用例独立会话（thread_id）。**
Agent 有记忆。如果两条用例共用一个会话，第二条就会带着第一条的上下文——**评测结果被记忆污染**。正确做法是每次调用生成独立 thread_id：

```python
return service.invoke(user_input=query, thread_id=f"eval-{uuid.uuid4()}", context=context)
```

**第三件：证据必须回传。**
被测系统要能把"这轮调了哪些工具、按什么顺序"吐出来。本期项目返回的 `tools_used` 和 `traces` 就是为此准备的。

---

## 四、动手：从 0 到 4 passed

### 4.1 环境

```bash
git clone https://github.com/yeyexue-rgb/langgraph_test.git
cd langgraph_test
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -U deepeval                          # 评测依赖单独装
```

`.env` 里配好模型（我用的是 DashScope 兼容端点）：

```
DASHSCOPE_API_KEY="你的 key"
DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME="qwen3.8-max"
```

### 4.2 跑

```bash
python scripts/seed_test_db.py                          # 造 ground truth 数据
pytest evals/test_agent_eval.py -m integration           # ① 单 Agent 架构
$env:EVAL_AGENT_MODE="subagents"; pytest evals/... -m integration   # ② 多 Agent 架构（Windows）
```

### 4.3 四条用例分别在测什么

| 用例 | 测什么 | 判据 | 成本 |
|---|---|---|---|
| SQL · P0 用例数量 | 数据查询链路 + 数量正确 | 出现 `3` + 工具正确 | 规则 + 指标 |
| 时间 · 相对时间解析 | 工具调用正确性（路由） | 出现 `15:00` + 调了时间工具 | 规则 + 指标 |
| 澄清 · 天气越界 | 能力边界（不编造） | 不出现虚构天气数据、不乱调工具 | 纯规则 |
| 安全 · 提示注入不泄露 | 安全底线 | 不出现 hosts 内容 | 纯规则 |

**注意最后两条：一条裁判都不用。** 规则能判死的场景，上裁判就是浪费钱。

### 4.4 光有"PASS"还不够：把分数和理由留档

默认情况下，DeepEval 只告诉你"通过/失败"，**不打印分数，也不打印裁判理由**——评测跑完仍是个黑盒。所以我在项目里加了一个留档器（`evals/eval_report.py`），跑完直接看到：

```
[用例] SQL · P0 用例数量（期望 3）
  指标                      score    阈值    结果    裁判理由
  ToolCorrectnessMetric     1.000    0.700   通过    All expected tools ['sql_db_query'] were called...
  TaskCompletionMetric      1.000    0.700   通过    ...providing the exact count (3)... perfectly aligning
[评测汇总] 架构=single 用例=4 指标通过=4/4 平均分=1.000
[评测留档] reports/eval-single-20260916-220413.json
```

**这一步的价值在于"可回溯"**：失败时你知道裁判为什么扣分；多次运行可以对比分数趋势（这就是评测回归）。

---

## 五、四个坑 + 一个隐藏缺陷

这部分最值钱，因为你大概率会踩一模一样的。

**坑 1：提示词被静默忽略。**
项目提示词放在 `prompts/*.md`，但加载器只认 `.txt`。结果：Agent 根本没吃到系统提示词，评测结论全是假的。**修法**：让加载器 `.md` 优先、兼容 `.txt`。
教训：**先验证"配置真的生效了"，再谈评测结论。**

**坑 2：类型不对，指标直接报错。**
DeepEval 4.x 要求 `tools_called` / `expected_tools` 是 `ToolCall` 对象，传字符串会 `TypeError`。
教训：指标库的入参类型要用 `LLMTestCase` 的实际定义去核对，别凭印象。

**坑 3：裁判模型悄悄走了 OpenAI。**
`ToolCorrectnessMetric` 不传 `model` 时会初始化默认裁判——直接报 `OpenAI API key is not configured`。**修法**：显式传自己的裁判（本期用 DashScope 的 qwen）。
教训：**每个会调 LLM 的指标，都要显式指定裁判模型**，否则你的 key 和成本都不受控。

**坑 4：断言绑死了架构。**
同一个用例，单 Agent 模式 `tools_used = ["parse_natural_datetime"]`，多 Agent 模式是 `["time_specialist", "parse_natural_datetime"]`（主管调包装工具 + 子 Agent 内部工具）。写成 `==` 相等，换个架构就假失败。**修法**：用 `in` 包含判断。
教训：**断言要跟架构解耦**，否则你测的是"架构"，不是"能力"。

**隐藏缺陷：模型偶发不吐结构化结果（这条最阴）。**
多 Agent 模式下，SQL 用例时好时坏，返回 `INVALID_SUBAGENT_RESULT`。我抓了子 Agent 的原始状态，发现失败时**最后一条是一条空 AI 消息（没有 tool_calls）**——模型跑完工具链，忘了调用"结构化输出"工具就结束了。**不是查询错，是模型抖动**，实测 3 次里挂 2 次。
修法给它加了一次重试，修完 **0/3 失败**。

> 这个案例值得单独说一句：**"评测失败"不等于"被测系统有缺陷"**。你要能区分：是模型的偶发抖动、是评测配置错了、还是产品真错了。这三种，处置方式完全不同。

---

## 六、零基础落地清单

照着打勾，你也能出一份能进 CI 的评测：

- [ ] 明确被测系统的调用入口（本项目：`evals/agent_provider.py` 统一入口）
- [ ] ground truth 有出处（种子数据 / 线上真实样本）
- [ ] 一条用例 = 输入 + 期望 + 证据 + 判定
- [ ] 规则层断言先跑，指标层后跑（省钱）
- [ ] 每条用例独立 thread_id（防记忆污染）
- [ ] 工具调用轨迹能回传（`tools_used` / `traces`）
- [ ] 裁判模型显式指定，并做人工校准
- [ ] 结果留档（分数 + 理由 → JSON），可对比趋势
- [ ] 断言与架构解耦（用包含，不用相等）

九条。前五条决定"评测对不对"，后四条决定"评测能不能长期用"。

---

## 七、写在最后

回到最初的立论：Agent 评测测的是**答案 + 过程**。把这句话落地，你需要的不是更聪明的模型，而是**四个零件 + 两层断言 + 一条可追溯的留档链**。

我从零把本期源码、种子数据、评测用例、留档补丁都跑通并验证过了：单 Agent 4 passed、多 Agent 4 passed。**这套东西你现在就能拿走，改成你自己的业务。**

> 🎁 **完整源码 + 网盘视频**：公众号后台回复「**agent**」，领取夸克网盘资源（含本期完整可运行源码、Seed 数据、评测配置）。
> 直达链接：**https://tinyurl.com/2cqnmtyq**

下一篇，我们把视角从"跑通"推到"看穿"：**多 Agent 架构下，怎么分别评估主管和子 Agent**。

---

### 附：本文对应的关键文件

| 文件 | 作用 |
|---|---|
| `evals/test_agent_eval.py` | 4 条评测用例（本文主角） |
| `evals/agent_provider.py` | 统一调用入口（评测与被测系统同源） |
| `evals/judge_model.py` | 自定义裁判（DashScope qwen） |
| `evals/eval_report.py` | 指标分数 + 裁判理由留档 |
| `scripts/seed_test_db.py` | 种子数据（ground truth 出处） |
