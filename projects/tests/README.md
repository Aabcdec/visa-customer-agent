# 测试（tests）

## 快速开始

```bash
cd projects

# 全量测试
python -m pytest -q

# 单个文件
python -m pytest tests/test_risk_assessment.py -v

# 只跑与风控有关的用例
python -m pytest -k risk -q

# 显示被标记为"已知缺口"的用例
python -m pytest -q -rx
```

> 也可以 `uv run pytest -q`。本机 Git Bash 下 `uv run` 偶发
> `uv trampoline failed to canonicalize script path`（MSYS 路径问题），
> 直接用 `.venv/Scripts/python.exe -m pytest` 更稳；CI 跑在 Linux 上不受影响。

## 为什么这些测试能完全离线

测试**不调用任何真实模型、不需要 API Key、不产生费用**。

做法分两类：

| 被测对象 | 做法 |
|---|---|
| 纯规则节点（风控 / 订单校验 / 投诉 / 订单查询 / 知识检索） | 直接调用节点函数，传入最小 `Runtime` 替身（`conftest.py` 的 `fake_runtime`） |
| LLM 节点与整张图 | 用 `eval/offline_runner.py` 把 3 个 LLM 节点替换成确定性桩 |

这样拆分的好处：规则逻辑出问题时，报错信息直接指向规则函数本身，
而不是被"图跑不起来"这类噪音淹没。

## 覆盖范围

| 文件 | 保护的东西 |
|---|---|
| `test_risk_assessment.py` | 高风险必转人工、中风险需确认、`flow_path` 优先级、**知识库正文不得触发风控** |
| `test_order_validation.py` | 整句提取订单号、格式校验、缺失时追问 |
| `test_order_progress.py` | 查不到**不编造**进度、插件异常兜底、Mock 数据字段完整 |
| `test_knowledge_retrieval.py` | 命中/不命中、阈值、排序、按结构化关键词拼查询 |
| `test_complaint_handoff.py` | 固定话术、必转人工、摘要含意图/国家/原话 |
| `test_graph_routing.py` | 三层路由函数、图结构、五类意图的端到端 `flow_path` |
| `test_api_contract.py` | `/health`、`/graph_parameter`、错误码、CORS |
| `test_dataset.py` | 评测集字段白名单、重复 id、假通过用例 |
| `test_evaluator.py` | 指标口径、精确率/召回率、`None` 语义、报告渲染 |
| `test_offline_runner.py` | 规则兜底意图、离线跑图、桩的还原 |

## 关于 `xfail(strict=True)`

有两处已知缺口用 `xfail(strict=True)` 显式记录，而不是删掉断言或静默跳过：

1. `test_out_of_domain_query_returns_nothing` — 域外问题缺少相关性门控
2. `test_previous_rejection_is_treated_as_medium_risk` — 「拒签」的高/中风险策略冲突

`strict=True` 的含义：**如果哪天有人修好了，测试会立刻失败**，逼着把标记改成正常断言。
这样"已知缺口"不会烂在那里被遗忘。

用 `-rx` 可以看到它们的 xfail 原因。

## 写新测试时的约定

1. **注释写「为什么」**，不要复述代码在做什么。
   例如"为什么要断言 required_materials 而不是 missing_slots"才是有价值的信息。
2. **测试名描述行为**，不要用 `test_works` 这类名字。
3. **优先断言可观察行为**（`flow_path`、回复内容、结构化字段），
   而不是内部实现细节，这样重构时测试不会误报。
4. **给边界和错误路径留位置**：空输入、类型错误、插件异常都要覆盖。
5. 新增"期望字段"时，需同步更新 `eval/dataset.py` 的白名单与 `eval/evaluator.py` 的 `CHECK_KEYS`，
   否则评测集会拒绝该字段。
