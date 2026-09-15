"""Agent 评测脚手架：promptfoo Provider + DeepEval 用例。

目录内容（对应《Agent 测试进阶实战（第二季）第 1 篇》的落地）：
- agent_provider.py：promptfoo Python Provider（黑盒接法"方式 2"），
  同时提供 invoke_agent() 供 DeepEval 复用，保证两个工具打同一个被测对象；
- promptfooconfig.yaml：single / subagents 双架构 A/B 评测配置 + 用例集；
- judge_model.py：DeepEval 裁判模型（LLM-as-judge 走 DashScope qwen）；
- test_agent_eval.py：DeepEval 评测用例（pytest 可直接跑）。

运行前提：
- .env 配置 DASHSCOPE_API_KEY；
- SQL 用例依赖种子库：python scripts/seed_test_db.py；
- DeepEval 用例需安装：pip install -U deepeval；
- promptfoo 为 Node CLI：npx promptfoo@latest ...（先激活项目 venv）。
"""
