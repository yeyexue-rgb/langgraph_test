"""Multi-Agent（Supervisor + Subagents）子包。

模块划分：
- contracts：子 Agent 内部结果契约 SubagentResult 与序列化适配；
- tracing：嵌套调用轨迹记录（SubagentTracer）与业务轨迹提取；
- time_specialist：时间领域子 Agent 及其 Supervisor 包装工具；
- file_specialist：文件领域子 Agent 及其 Supervisor 包装工具。

设计原则（与系列文章对齐）：
- domain/ 与 providers/ 的确定性业务逻辑零改动；
- 子 Agent 无 checkpointer、无独立记忆，每次调用使用干净上下文；
- SQLite 记忆与 thread_id 只归 Supervisor 管理；
- 安全边界留在工具层（_safe_directory），HITL 审批挂在 Supervisor
  编排层拦截 file_specialist 的越界调用。
"""
