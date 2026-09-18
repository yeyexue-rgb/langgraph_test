# 打开 Agent 黑匣子：Langfuse 轨迹追踪实战

> Agent 测试进阶实战（第二季）· 实战篇 03
> 配套源码：https://github.com/yeyexue-rgb/langgraph_test（本次改造已提交说明见文末）

---

## 一、评测告诉你「过没过」，追踪告诉你「发生了什么」

上一期我们聊了怎么判断"评测红了到底谁错了"。这一期往前推一步：**当评测只给你"通过/失败"两个字时，你怎么知道过程里发生了什么？**

评测和追踪，回答的是两个不同的问题：

| 维度 | 评测（DeepEval） | 追踪（Langfuse） |
|---|---|---|
| 回答的问题 | 这次**过没过**？质量达标吗？ | 这次**发生了什么**？慢在哪、错在哪一步？ |
| 输出 | 分数 / 通过率 | 完整调用树：谁调了谁、耗时、token、入参出参 |
| 覆盖范围 | 你写了的用例 | 线上**全部**真实流量 |
| 使用时机 | 发版前、CI 里 | 出问题时、性能劣化时、日常巡检 |
| 成本 | 每条用例都要钱（裁判） | 按采样比例，可压到很低 |

一句话：**评测是守门员，追踪是行车记录仪。**

守门员只能守你安排他守的那几脚球；行车记录仪是你出事后唯一能回看现场的东西。**两者缺一不可——只有评测，你会漏掉没写用例的场景；只有追踪，你没有"通过线"。**

---

## 二、三个概念，先弄明白再动手

Langfuse 的数据模型不复杂，记住三层就够：

**① Trace（一次会话/一次请求）**
你问一句、Agent 答一句，整个链路算一条 Trace。我们在代码里把 `thread_id` 映射成 Trace 的 session，这样**同一轮对话的多次调用能串起来**。

**② Span（一次运行步骤）**
Trace 内部的节点。比如多 Agent 架构里：
```
Trace: "帮我查下这个月 P0 用例有多少"
├── Span: supervisor（主管思考）
│   ├── Span: sql_specialist（子 Agent）
│   │   ├── Span: sql_db_list_tables
│   │   ├── Span: sql_db_schema
│   │   └── Span: sql_db_query  ← 真正查数据的地方
│   └── ...
└── Span: 最终结构化输出
```
**Span 树就是 Agent 的"行车轨迹"。** 谁是瓶颈、哪一步多余，一眼就能看出来。

**③ Generation（一次模型调用）**
Span 里调用大模型的那一步，额外记录 **token 数、成本、模型名、完整 prompt 与输出**。

有了这三层，你就能回答那些"评测答不了"的问题。

---

## 三、实战：给 Agent 接上 Langfuse（不改业务代码）

下面这套改造已经落到仓库里，可以照着抄。核心设计原则是三条：**可选、零侵入、默认脱敏**。

### 第 1 步：装依赖 + 配环境变量

```bash
pip install -r requirements-observability.txt   # 内部就是 langfuse>=4.0.0
```

`.env` 里加（仓库已附 `.env.example`）：

```
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_HOST="https://cloud.langfuse.com"   # 自托管改成自己的地址
LANGFUSE_SAMPLE_RATE=1.0                     # 采样比例，压成本时调小
LANGFUSE_MASK=1                              # 敏感信息脱敏（默认开）
```

**注意**：不配 `LANGFUSE_*` 时，整套东西**完全不起作用**——这是刻意的，见第 4 步。

### 第 2 步：新增一个可观测性模块（`agent_core/observability.py`）

它对外只有几个函数，负责"该不该追踪、怎么建回调、怎么脱敏、怎么收尾"：

```python
def langfuse_enabled() -> bool:
    """显式开关优先；没配 key 一律视为关闭。"""
    has_keys = bool(_env("LANGFUSE_PUBLIC_KEY") and _env("LANGFUSE_SECRET_KEY"))
    explicit = _env("LANGFUSE_ENABLED")
    return (_flag("LANGFUSE_ENABLED") and has_keys) if explicit else has_keys

def should_trace() -> bool:
    """未启用 / 未命中采样 → 本次不追踪。"""
    if not langfuse_enabled():
        return False
    rate = sample_rate()
    return True if rate >= 1.0 else random.random() < rate
```

脱敏默认开着——**别把 API Key、绝对路径写进追踪平台**：

```python
_SECRET_PATTERNS = (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), ...)
_PATH_PATTERNS = (re.compile(r"[A-Za-z]:\\[^\s\"']+"), re.compile(r"/(?:home|Users|root|tmp)/[^\s\"']+"))
```

### 第 3 步：把回调挂到运行配置上（关键的一步）

重点：**我们完全没动 Agent 的构建逻辑，只在运行配置里"顺路"挂了一个回调。**

```python
def _attach_tracing(self, config, *, thread_id, context=None):
    if self.langfuse_handler is None or not should_trace():
        return config                      # ← 未启用：原样返回，零开销

    tracing = trace_config(
        thread_id=thread_id,
        user_id=getattr(context, "user_id", None),
        tenant_id=getattr(context, "tenant_id", None),
        agent_mode=self.agent_mode,
    )
    merged = dict(config)
    merged["callbacks"] = list(config.get("callbacks", [])) + tracing.pop("callbacks")
    merged.update(tracing)
    return merged
```

调用处只加一行：

```python
config = self._attach_tracing(self._build_config(thread_id), thread_id=thread_id, context=context)
```

### 第 4 步：把 thread_id 映射成会话（这一步最值钱）

```python
return {
    "callbacks": [handler],
    "run_name": f"agent-{agent_mode}",
    "tags": tags,
    "metadata": {
        "langfuse_session_id": thread_id,     # 同一轮对话串成一条 session
        "langfuse_user_id": user_id,
        "langfuse_tags": tags,                # mode:single / mode:subagents / tenant:xx
        "agent_mode": agent_mode,
    },
}
```

**为什么要这么做？** 因为这样你就能在平台上按"**架构模式**"筛选、按"**用户**"聚合。多 Agent 上线那天，你可以直接对比 `mode:single` 和 `mode:subagents` 的耗时与成功率分布——这比评测用例给你的信息量大得多。

### 第 5 步：脚本收尾 flush（别丢数据）

```python
from agent_core.observability import flush
...
flush()   # 进程即将退出时推一把
```

Langfuse 是**异步批量上报**的。常驻 Web 服务不用管；但**脚本、定时任务、CI 跑完就退出**，收尾必须 flush，否则数据还没发出去进程就没了。

### 第 6 步：冒烟验证

```bash
python scripts/langfuse_smoke.py "当前一共有多少条 P0 优先级的测试用例？"
```

真实运行输出（未配 Langfuse 时）：

```
追踪开关     : 关（未配置 LANGFUSE_*，零影响）
回调处理器   : 未创建（no-op）
被测架构     : single
--------------------------------------------------------------
问题         : 当前一共有多少条 P0 优先级的测试用例？
状态         : success
回答         : 当前一共有 3 条 P0 优先级的测试用例。
工具轨迹     : ['sql_db_list_tables', 'sql_db_schema', 'sql_db_query_checker', 'sql_db_query']
本轮耗时     : 11221 ms
```

**注意"零影响"这三个字。** 没配 key 时，Agent 行为与改造前**逐字节一致**——这条是被回归测试守住的（`pytest tests -m "not integration"` → 176 passed）。

---

## 四、打开黑匣子之后，你能看到什么

配好 key 再跑一次，平台上会出现一棵完整的树：

```
session: eval-8f3c...        [mode:subagents] [tenant:qa-team]
└── agent-subagents                              11.2s   ¥0.0041
    ├── supervisor                               3.1s   2,148 tokens
    │   └── sql_specialist                       6.8s
    │       ├── sql_db_list_tables               0.3s
    │       ├── sql_db_schema                    0.4s
    │       ├── sql_db_query_checker    ← LLM    2.1s   612 tokens
    │       └── sql_db_query                     0.2s   → [(3,)]
    └── 结构化输出                               0.6s
```

第一次看到这棵树的时候，我说实话有点震撼：**原来一次"查询"背后有这么多步，而且大部分时间花在两个地方——模型思考（supervisor 3.1s + checker 2.1s），而不是查数据（0.2s）。**

**这就是黑匣子的价值：你的直觉和事实经常相反。**

---

## 五、三个马上就能用起来的场景

### 场景一：定位"慢在哪"

以前用户说"你这个 Agent 好慢"，你只能猜。
现在你能直接回答：**87% 的时间花在两次模型调用上，SQL 查询只占 0.2 秒。**

有了这个结论，优化方向就明确了：能不能把 `sql_db_query_checker` 这步省掉？能不能换更小的模型？——而不是盲目地去优化数据库。

### 场景二：定位"错在哪一步"

同一个问题，两条轨迹摆在一起对比：

| | 正常轨迹 | 异常轨迹 |
|---|---|---|
| 第 1 步 | `sql_db_list_tables` ✅ | `sql_db_list_tables` ✅ |
| 第 2 步 | `sql_db_schema` ✅ | `sql_db_schema` ✅ |
| 第 3 步 | `sql_db_query` ✅ → `[(3,)]` | **直接结构化输出** ❌ |
| 结果 | 3 条 | 编造答案 |

**差异点在第 3 步：模型跳过了查询，直接作答。** 这是评测永远给不出的信息——评测只说"这条没过"，追踪告诉你"它在哪里抄了近道"。

上一期我们花大力气定位的那个"模型偶发不吐结构化结果"的缺陷，如果有追踪，排查时间能从两小时缩短到两分钟。

### 场景三：把线上 badcase 回灌成评测用例（闭环）

这是追踪最被低估的用法：

```
线上真实流量 → 追踪记录 → 筛出"用户不满意/评分低"的轨迹
                            ↓
                     复现成评测用例（输入+期望+证据）
                            ↓
                    进评测集 → 守门员从此盯住它
```

**评测集不该拍脑袋造，应该从真实轨迹里"长"出来。** 你跑一周追踪，筛出 20 条烂 case，就是 20 条最有价值的评测用例——比你闭门造 200 条都管用。

---

## 六、顺手修掉的三个仓库问题

改造过程中我发现仓库里有三处"实现和测试对不上"的老问题（都是 `pytest` 直接报错的那种），一并修了：

| 问题 | 现象 | 修法 |
|---|---|---|
| `prompt_manager` API 不完整 | 测试导入 `PROMPT_NAMES` / `PromptManager` 直接 ImportError | 补齐完整 API：目录优先级（显式 > 环境变量 > 默认）、场景白名单、空文件报错 |
| 轨迹缺"用户输入"前置条目 | 测试按下标断言拿不到预期值 | 轨迹结构补上 `user_input` 首条，保证能完整回放一轮对话 |
| SQL 服务层错误处理不一致 | 单元测试要求"拒绝写操作"**抛异常**，服务层测试要求**返回提示** | 校验函数照旧抛 `ValueError`，`execute_query` 捕获后返回提示（工具层才能如实转述） |

修完：**`pytest tests -m "not integration"` → 176 passed。**

> 这三处都是"测试是对的、实现漏了"的典型案例。**测试跑不过的时候，先别改测试。**

---

## 七、四个坑（都是我自己踩的）

**坑 1：忘了 flush。**
脚本跑得好好的，平台上一片空白。Langfuse 异步批量上报，**短生命周期进程必须显式 flush**。

**坑 2：采样率拍脑袋设 0.1。**
省钱了，但**恰好你想复盘的坏 case 被采样掉了**。建议：初期全量（或 0.5 以上），等你看清成本结构再压。

**坑 3：把密钥写进了追踪。**
追踪平台会记录完整的 prompt 和工具入参。**如果你的 prompt 里带 key、带用户手机号，那就是在往平台里写敏感数据。** 所以脱敏默认开着，别图省事关掉。

**坑 4：以为"不追踪就不消耗"。**
回调处理器本身有开销（很小，但不是零）。所以我们把 `should_trace()` 放在**最前面**——未启用时连回调对象都不创建，彻底零开销。

---

## 八、写在最后

回到那句话：**评测是守门员，追踪是行车记录仪。**

- 守门员让你有底气发版（"我的用例都过了"）；
- 行车记录仪让你有底气面对**没预料到的问题**（"我知道现场发生了什么"）。

**只有评测的团队，遇到没写用例的故障时会慌；配上追踪的团队，遇到任何故障都先去看现场。**

本期改造已经落到仓库：`agent_core/observability.py`（新增）、`agent_service.py`（+1 行挂载）、`scripts/langfuse_smoke.py`（冒烟）、`requirements-observability.txt`、`.env.example`。

> 🎁 **完整源码 + 改造 patch**
> 公众号后台回复「**agent**」，领取夸克网盘资源（含本期 Langfuse 改造代码、冒烟脚本与配置模板）。
> 直达链接：**https://tinyurl.com/2cqnmtyq**

下一篇预告：**把评测、追踪、线上监控串成一条质量流水线**——什么时候跑评测、什么时候看追踪、出问题按什么顺序排查。

---

### 附：本次改造文件清单

| 文件 | 类型 | 作用 |
|---|---|---|
| `agent_core/observability.py` | 新增 | Langfuse 接入层（开关/采样/脱敏/回调/收尾） |
| `agent_core/agent_service.py` | 修改 | `_attach_tracing()` 挂载追踪（未启用时零开销） |
| `scripts/langfuse_smoke.py` | 新增 | 一行命令跑通端到端追踪 |
| `requirements-observability.txt` | 新增 | 可选依赖（langfuse>=4.0.0） |
| `.env.example` | 新增 | 配置模板（含 Langfuse 段） |
| `agent_core/prompt_manager.py` | 修复 | 补齐 API，消除 ImportError |
| `agent_core/subagents/tracing.py` | 修复 | 轨迹补 `user_input` 前置条目 + 忽略非法状态 |
| `providers/sql_provider.py` | 修复 | 服务层拒绝写操作时返回提示而非抛异常 |
