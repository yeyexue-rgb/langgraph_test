# 别再手搓评测脚本了：promptfoo + DeepEval，30 分钟上手

> **Agent 测试进阶实战（第二季）· 第 1 篇**
> 阅读对象：测试工程师 / QA / SDET ｜ 预计阅读：10 分钟
> 本篇目标：把"手搓评测脚本"升级成工具化评测——两个主流开源工具，各 30 分钟跑通，直接接进你的工作流
> 延续：第一季讲了"要测什么"（五维/轨迹/基准），本季讲"用什么测、怎么测得更省力"

---

先描述一个你大概率经历过的场景。

老板说："下周给 Agent 出个评测报告。"

于是你：打开 Excel，手动跑 20 条问题，人肉判断对错，截图贴进去，写几句结论——交差。下周再跑一遍，发现：**上一版没有留档、两条结果没法比、换个人来跑标准又不一样。**

问题不在你不够努力，而在**用手工业的方式，做工业化的事**。

评测这件事，行业里早就有成熟工具：**promptfoo** 和 **DeepEval**。它们不是"又一个新概念"，而是两个能让你**少写脚本、多做判断**的家伙——而"做判断"，正是测试工程师最值钱的部分。

这篇不聊虚的，两件事：**① 两个工具分别是什么、怎么选；② 各 30 分钟，跑通你的第一套自动评测。**

## 一、先把概念搞清楚（这步别省）

很多人一上来就问"哪个更强"，其实它们分工不同：

**promptfoo —— 命令行评测 + 红队工具。**
配置驱动（一个 YAML 文件），适合快速搭建评测、对比不同模型/Prompt、以及做**红队测试**（自动生成注入、越权、泄密这类攻击用例）。官方定位很直白：*test your prompts, agents, and RAGs*，既能评测也能"红队扫描"。

**DeepEval —— "面向 LLM 的 Pytest"。**
Python 生态、指标即断言。官方定位就是"*Pytest for LLMs*"：你熟悉的 `pytest` 写法，直接套在 LLM/Agent 上，跑出**工具调用准确率、任务完成度、忠实度**这些指标。

**一句话怎么选（先别纠结）：**
- 想**快速起步、多模型对比、顺手做安全红队** → 先上 promptfoo；
- 团队已经在 **pytest/CI 体系**里、想要细粒度指标评分 → 上 DeepEval；
- 两者不冲突，**可以同时用**（后面给你组合方案）。

![图1｜promptfoo 与 DeepEval 分工](figs/fig-s2a-tools.png)

**图1｜一个管"快速评测 + 红队"，一个管"指标化 + pytest 体系"**

## 二、30 分钟上手 promptfoo（你来做第一套评测）

**第 1 步 · 安装与初始化（2 分钟）**

```bash
npx promptfoo@latest init      # 生成 promptfooconfig.yaml 模板
# 或用 Python: pip install promptfoo
```

**第 2 步 · 写配置（10 分钟）**——一个文件说明白"测什么、怎么判"：

```yaml
providers:
  - id: openai:gpt-4o-mini          # 也可以换成你的 Agent 接口
prompts:
  - "你是客服，回答用户问题：{{query}}"
tests:
  - vars:
      query: "我的订单到哪了？"
    assert:
      - type: contains
        value: "订单"                 # 关键事实必须出现
      - type: not-contains
        value: "已签收"               # 禁止编造物流状态
      - type: llm-rubric
        value: "回答应礼貌且不编造信息"   # 主观维度：让 LLM 当裁判
```

**第 3 步 · 跑评测（2 分钟）**

```bash
promptfoo eval          # 命令行跑完，出通过率表格
promptfoo view          # 打开可视化界面，逐条看失败原因
```

**第 4 步 · 顺手做一次红队（10 分钟）**——这是大多数团队从没做过、却能立刻加分的一步：

```bash
promptfoo redteam init    # 生成红队配置
promptfoo redteam run     # 自动生成攻击用例并执行（注入/越权/泄密等）
```

跑完你会拿到一份"安全体检报告"：哪些攻击成功了、风险等级如何。

**第 5 步 · 接进 CI（5 分钟）**——用官方 GitHub Action，让每次改 Prompt 都自动跑一遍评测。

> **👩‍💻 你在这里的产物**：一份 `promptfooconfig.yaml`（团队资产）+ 一份评测报告 + 一份红队报告。**没有写一行业务脚本，三样东西全有了。**
MDEOF
echo ok
## 三、看不到源码怎么办？黑盒测试工程师的用法（重点）

先给结论：**promptfoo 不需要源码。** 它是黑盒评测工具——你只需要一个前提：**能调用到 Agent**。三种接法，从最省事到最兜底：

**方式 1 · HTTP Provider（推荐，零代码）**
Agent 有接口？把地址填进配置就行，一个 YAML 搞定：

```yaml
providers:
  - id: https
    config:
      url: 'https://your-agent.example.com/chat'    # 你们 Agent 的接口
      method: 'POST'
      headers:
        'Content-Type': 'application/json'
        'Authorization': 'Bearer {{env.AGENT_TOKEN}}'
      body:
        message: '{{query}}'                         # 测试用例里的变量
      transformResponse: 'json.data.reply'           # 从响应里取出“回答”字段
tests:
  - vars: { query: "我的订单到哪了？" }
    assert:
      - { type: contains, value: "订单" }
      - { type: not-contains, value: "已签收" }
```

**方式 2 · 自己写几行代码当 Provider（灵活）**
接口要签名、要加密、要多步调用？写个 Python 文件，promptfoo 直接调它：

```python
# agent_provider.py —— 你只需要这十来行
import requests
def call_api(prompt, options, context):
    resp = requests.post("https://your-agent/chat",
                         json={"message": prompt}, timeout=30)
    return {"output": resp.json()["data"]["reply"]}
```

配置里写一行 `providers: - id: 'file://agent_provider.py'` 就接上了。

**方式 3 · 只有页面、没有接口？（兜底）**
用 exec/脚本 Provider 包一层：脚本里用 Playwright 打开页面、输入、抓回复，再把结果输出出去。**全程不碰源码，操作的是你自己能看到的界面。**

![图2｜看不到源码时的三种接法](figs/fig-s2c-blackbox.png)

**图2｜三种黑盒接法：HTTP / Python / 脚本兜底**

**那“轨迹/工具调用”看不到怎么办？**
两个动作：① **推动研发把轨迹暴露出来**——第一季就说过，“轨迹可导出”是测试工程师该提的需求；② 拿不到时，只断言**可观测的部分**：回答内容、报错情况、响应时间、重复执行的表现；把“行为合理性”这一维暂时降级为“可观测行为”——比如把“查询场景不得触发发送动作”改成“回答里不得出现‘已发送’字样”。

**记住：黑盒不是限制，是常态。** promptfoo 本来就是给黑盒用的工具；需要源码的，是单元/编排层的替身测试——那是另一套活儿。

## 四、30 分钟上手 DeepEval（用你熟悉的 pytest 方式）

如果你本来就是写 pytest 的，这个工具会让你有种"回家了"的感觉——它的官方定位就是 **"Pytest for LLMs"**。

**第 1 步 · 安装（1 分钟）**

```bash
pip install -U deepeval
```

**第 2 步 · 写第一条评测用例（15 分钟）**

```python
from deepeval import assert_test
from deepeval.test_case import LLMTestCase
from deepeval.metrics import TaskCompletionMetric, ToolCorrectnessMetric

def test_order_query_agent():
    case = LLMTestCase(
        input="我的订单到哪了？",
        actual_output="您的订单已揽收，预计明天送达",
        expected_tools=["query_order", "query_logistics"],
        tools_called=["query_order", "query_logistics"],
    )
    # 指标即断言：任务完成度 + 工具调用正确性
    assert_test(case, [TaskCompletionMetric(threshold=0.7),
                       ToolCorrectnessMetric()])
```

**第 3 步 · 跑起来（2 分钟）**

```bash
deepeval test run test_agent.py     # 或在 pytest 里直接跑
```

注意第二个指标：**ToolCorrectness（工具调用正确性）**——这是它比"只看输出"高明的地方：**它把"过程"也纳入了断言**，正好对应第一季讲的"结果对 ≠ 过程对"。

**第 4 步 · 指标怎么用才准（12 分钟，概念别搞混）**

DeepEval 的指标分两类，用法完全不同：
- **规则类**：如工具调用比对——确定性、便宜、必须先用；
- **裁判类**（LLM-as-judge）：如任务完成度、忠实度——主观维度用它，但**必须用人工标注集定期校准**，否则就是个"好好先生"。

> **👩‍💻 你在这里的产物**：一套可进 pytest 的评测用例 + 指标分数报告。**和你现有的测试体系无缝衔接——这是其他工具比不了的。**

> **👩‍💻 黑盒也能用**：DeepEval 只是个 Python 库——写几行代码调用 Agent 的 HTTP 接口，把响应包进 `LLMTestCase` 再断言即可。如果拿不到“工具调用”信息，就先用输出侧指标（任务完成度等），同时推动研发暴露轨迹。

## 五、你的工作流：两个工具怎么分工（测试工程师主场）

工具选好了，接下来是"怎么干得像个专业团队"。给你一套可以直接落地的分工：

| 环节 | 用哪个 | 你做什么（重点） |
|---|---|---|
| 用例从哪来 | 都要 | **线上日志采样 + 事故复现 + 对抗用例**（第一季的老方法） |
| 快速对比 / 选型 | promptfoo | 定变量、看通过率差异，输出选型建议 |
| 安全体检 | promptfoo redteam | 跑一遍，把风险项转成回归用例 |
| 回归指标化 | DeepEval | 把关键指标编成 pytest 用例，进 CI |
| 门禁 | 两者接 CI | **成功率阈值**卡合入；失败自动建单 |
| 报告 | 两者都出 | 趋势图进周会：**用数据说话** |

**一句话总结分工**：**工具替你跑，判断留给你。** 评测工具能自动生成用例、自动打分，但"什么算通过""风险能不能接受""这个偏差要不要拦"——这些判断，永远是你的活。

![图3｜测试工程师的评测工作流](figs/fig-s2b-workflow.png)

**图2｜你的工作流：采样 → 双工具评测 → CI 门禁 → 周会报告**

## 六、四个坑（都是别人踩过的）

1. **裁判不校准。** LLM-as-judge 不用人工标注集校准，分数会"虚高且漂移"——第 3 篇（红队）还会遇到同类问题；
2. **只测输出，不看过程。** 只会 `contains`，就会漏掉"结果对、过程歪"。用 ToolCorrectness 或轨迹断言补上；
3. **评测集污染。** 老题目被模型"背过"，分数好看但没意义——定期换新题；
4. **CI 直连真模型烧钱。** 白天的 PR 用抽样/替身跑，全量留给夜间和发布前。

## 七、一页速查（截图存下来）

| 维度 | promptfoo | DeepEval |
|---|---|---|
| 形态 | CLI + YAML 配置 | Python 库（pytest 风格） |
| 上手门槛 | 会写 YAML 就行 | 会写 pytest 就行 |
| 强项 | 多模型对比、红队、可视化 | 细粒度指标、工程化回归 |
| 断言方式 | YAML 断言（contains/llm-rubric…） | 指标即断言（阈值判定） |
| 红队 | ✅ 内置 redteam | 生态另有 deepteam |
| CI | 官方 GitHub Action | 原生 pytest 集成 |
| 适合谁 | 快速起步 / 安全扫描 | 已有 pytest 体系的团队 |

**常用命令**：`npx promptfoo init / eval / view / redteam run`；`deepeval test run xxx.py`。

## 写在最后

这篇文章没有讲任何"新概念"——评测、断言、门禁，全是你干了多年的老本行。

变的只是：**以前你用 Excel 和手写脚本干这些，现在用两个工具，半小时搭好，还能进 CI。**

工具替你跑，判断留给你。**当别人还在手搓脚本的时候，你已经在用工程化的方式交付评测了——这就是测试工程师在新赛道上的位置。**

下一篇，我们把 Agent 的"黑匣子"打开：**用 Langfuse 做轨迹追踪**——每一步调了什么、哪一步开始跑偏，一屏看穿。

🎬 **配套彩蛋**：想要本文两个工具的**开箱即用配置**（promptfoo 配置模板 + DeepEval 用例脚手架 + CI 配置片段）？我把实操演示《**AI 在测试领域应用的探索**》一起打包了——**公众号后台回复「agent」即可自动获取**。

觉得有用，点个**赞 + 在看**，转发给还在"手搓评测脚本"的同事。评论区聊聊：你们团队现在用什么工具跑 Agent 评测？

---

**参考资料**：工具定位与用法参照 promptfoo 官方文档（test prompts, agents and RAGs / red teaming）、DeepEval 官方文档（"Pytest for LLMs"、ToolCorrectness / TaskCompletion 等指标）。
