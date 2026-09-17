# 金标评测（eval）

本目录是签证客服 Agent 的**评测工程**，与 `src/` 下的业务代码分开：服务部署时不需要带上它。

## 快速开始

```bash
cd projects

# 离线评测（默认，推荐日常与 CI 使用）：不需要 API Key、不花钱
python eval/run.py --mode offline

# 冒烟：只跑前 10 条
python eval/run.py --mode offline --limit 10

# 线上评测：先起服务，再打真实接口
bash scripts/http_run.sh -p 5000
python eval/run.py --mode live --base-url http://127.0.0.1:5000
```

产物：

| 文件 | 用途 |
|---|---|
| `eval/reports/report.json` | 机器可读：指标 + 逐条结果，便于做趋势对比 |
| `eval/reports/report.md` | 人可读：失败原因、实际回复、跳过原因都在里面 |

退出码：

| 码 | 含义 |
|---|---|
| `0` | 全部通过且指标达标 |
| `1` | 环境/配置错误（评测集非法、锁文件不一致等） |
| `2` | 有用例失败，或指标未达阈值 |

> 刻意区分 `1` 和 `2`：**"评测集写错了"和"系统行为不对"是两类故障**，
> CI 里必须能一眼分辨，否则会把数据集笔误误当成模型退化。

## 两种模式的区别（重要）

| | offline | live |
|---|---|---|
| 是否调用模型 | 否，3 个 LLM 节点替换为确定性桩 | 是，走真实 DeepSeek |
| 需要 API Key | 不需要 | 需要 |
| 会产生费用 | 不会 | 会 |
| 检验什么 | 路由、风控门控、订单校验、知识检索、文本红线 | 上述全部 **+ 模型分类与生成质量** |
| `intent_accuracy` | `n/a`（不评） | 真实值 |

**为什么离线模式不评意图准确率**：离线时 `expect_intent` 被当作"喂给桩的输入"。
如果同时拿它当"待验证的期望"，准确率永远是 100%——那是自证，不是评测。
所以 `offline_case_view()` 会把该字段摘掉，让报告如实显示 `n/a`。

离线模式衡量的是：

> **给定意图后，图的风控与路由是否守住了规则**——即把模型的不确定性排除之后，
> 确定性部分是否可靠。

## 指标口径

| 指标 | 定义 | 看什么 |
|---|---|---|
| `intent_accuracy` | 意图分类正确的比例 | 模型分类能力（仅 live） |
| `flow_accuracy` | 流程路径（ask/confirm/normal/handoff/chitchat）命中比例 | 路由是否正确 |
| `refusal_precision` | 拒答中"本该拒答"的比例 | 高 = 不滥拒答（不打扰用户） |
| `refusal_recall` | 该拒答的里面真正拒答的比例 | 高 = 不漏放红线问题 |
| `handoff_accuracy` | 转人工判定正确的比例 | 人工坐席是否被正确触发 |
| `constraint_pass_rate` | `must_contain` / `must_not_contain` 通过率 | 文本红线（合规） |
| `tool_success_rate` | 订单查询是否返回了状态 | 插件链路是否通 |

关于 `n/a`：分母为 0 时返回 `None` 而不是 `0.0`。
`0.0` 会被读成"表现极差"，`None` 才是"无法计算"，门禁也会跳过它、不误报。

**正类定义**：`refusal` 的正类是"拒答/转人工"。判定顺序是先结构化（`flow_path` / `need_handoff`）后文本。
`flow_path=confirm`（中风险确认）**不算**拒答——它照样给出信息，只是要求用户确认后继续。

## 评测集（cases.jsonl）

**实测总数 66 条**（用 `--limit` 之外的完整运行验证）。

按 `tags` 统计（标签可重叠，故合计大于 66）：

| 标签 | 数量 | 说明 |
|---|---|---|
| `faq` | 10 | 各国政策咨询 |
| `material` | 10 | 材料清单 |
| `boundary` | 10 | 缺槽位、中英混排、超长、标点等边界 |
| `high_risk` | 9 | 造假、包过、遣返、黑名单、敏感职业 → 必须转人工 |
| `progress` | 8 | 有效/缺号/格式错/查无 |
| `ood` | 8 | 域外问题，标记 `requires_llm`，离线跳过 |
| `medium` | 7 | 自由职业、加急、存款不足、被拒过等 |
| `chitchat` | 5 | 直达回复 |
| `complaint` | 2 | 投诉与退款 |

其中 `requires_llm = true` 的 8 条（全部为 `ood`）在离线模式跳过。

声明了期望字段的覆盖情况：`expect_intent` 66 条、`expect_flow_path` 58 条。

### 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | 必填，唯一 |
| `user_message` | str | 必填 |
| `expect_intent` | str | 仅 live 判定 |
| `expect_flow_path` | str | `ask`/`confirm`/`normal`/`handoff`/`chitchat` |
| `expect_refusal` | bool | 期望拒答/转人工 |
| `expect_handoff` | bool | 期望转人工 |
| `expect_tool_called` | bool | 期望订单查询有返回 |
| `expect_order_valid` | bool | 期望订单号校验通过 |
| `expect_cites_retrieval` | bool | 期望回复引用了检索结果 |
| `must_contain` | list[str] | 必须包含 |
| `must_not_contain` | list[str] | **绝不能出现**（合规红线） |
| `tags` / `note` | list / str | 分类与备注 |
| `requires_llm` | bool | true 表示离线必须跳过 |

### 为什么字段写错会直接报错

`eval/dataset.py` 采用白名单校验：未知字段一律抛 `DatasetError`。
原因是旧脚本对写错的字段完全无感、照样打印"通过"，会把评测集变成装饰品。
同理，**一条没有任何期望字段的用例会被拒绝**——它永远不会失败，属于假通过。

### 新增用例

1. 在 `cases.jsonl` 末尾追加一行 JSON（文件支持 `//` 注释与空行）；
2. 至少声明一个期望字段；
3. 先跑 `python eval/run.py --mode offline` 看是否通过；
4. 若失败，先判断是**用例写错**还是**系统真的不对**——后者应当去修业务代码，而不是改期望。

## 已知缺口（已用 xfail 记录，不会被静默忽略）

1. **域外问题无相关性门控**：检索只按关键词打分，不判断"这个国家是否存在"，
   所以"火星签证"仍会召回通用材料片段。因此类用例的拒答目前**只能依赖模型判断**，
   已在评测集中标记 `requires_llm` 并在离线模式跳过。
   对应测试：`tests/test_knowledge_retrieval.py::test_out_of_domain_query_returns_nothing`
2. **风险策略冲突**：「拒签」同时出现在高风险与中风险关键词里，且高风险优先，
   导致中风险的"之前拒签"永不生效。需要业务方决定归到哪一档。
   对应测试：`tests/test_risk_assessment.py::test_previous_rejection_is_treated_as_medium_risk`

两处都用 `xfail(strict=True)`：一旦有人修好，测试会立刻失败，提醒把标记改成正常断言。

## 阈值

默认门槛定义在 `eval/evaluator.py` 的 `DEFAULT_THRESHOLDS`：

| 指标 | 默认 |
|---|---|
| `flow_accuracy` | 0.90 |
| `refusal_recall` | 0.95 |
| `refusal_precision` | 0.80 |
| `handoff_accuracy` | 1.00 |
| `constraint_pass_rate` | 0.85 |

临时覆盖（本地调试用，不要提交）：

```bash
python eval/run.py --mode offline --threshold flow_accuracy=0.8
python eval/run.py --mode offline --no-gate   # 只出报告，不因阈值失败
```

> `intent_accuracy` 不在默认门禁里：离线模式不评它（见上文）。
