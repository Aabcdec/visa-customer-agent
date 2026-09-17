## 项目概述
- **名称**: 签证客服助手-Demo
- **功能**: 签证咨询与材料引导工作流，支持意图分类、知识库检索、槽位填充、风险评估、订单进度查询，输出结构化回复

### 节点清单
| 节点名 | 文件位置 | 类型 | 功能描述 | 分支逻辑 | 配置文件 |
|-------|---------|------|---------|---------|---------|
| intent_classify | `nodes/intent_classify_node.py` | agent | LLM意图分类，提取国家/签证类型/订单号 | - | `config/intent_classify_llm_cfg.json` |
| knowledge_retrieval | `nodes/knowledge_retrieval_node.py` | task | 本地知识库（assets/*.md）关键词检索签证信息 | - | - |
| slot_filling | `nodes/slot_filling_node.py` | agent | 检查并补充缺失信息槽位 | - | `config/slot_filling_llm_cfg.json` |
| risk_assessment | `nodes/risk_assessment_node.py` | task | 风险门控：高风险handoff、中风险confirm、缺信息ask、否则normal；统一写flow_path | - | - |
| order_progress_query | `nodes/order_progress_query_node.py` | task | Mock插件查询签证订单进度 | - | - |
| response_generate | `nodes/response_generate_node.py` | agent | 综合上下文生成结构化回复 | - | `config/response_generate_llm_cfg.json` |

**条件分支**: intent_classify → route_by_intent
- "检索知识库" → knowledge_retrieval (country_inquiry/material_check/risk_consultation)
- "查询订单进度" → order_progress_query (progress_query)
- "直接生成回复" → response_generate (other)

**类型说明**: task(task节点) / agent(大模型) / condition(条件分支) / looparray(列表循环) / loopcond(条件循环)

## 工具清单
| 工具名 | 文件位置 | 功能描述 | 被调用节点 |
|-------|---------|---------|----------|
| query_order_progress | `tools/order_progress_tool.py` | Mock签证订单进度查询插件 | order_progress_query |

## 知识库
- 本地 markdown 关键词检索（`utils/knowledge.py`，按二级标题分节+关键词打分）
- 文档: `assets/countries_faq.md`（各国签证FAQ）
- 文档: `assets/material_checklist.md`（签证材料清单）
- 文档: `assets/risk_policy.md`（风险评估政策）

## 会话状态变量
| 变量名 | 类型 | 说明 |
|-------|------|------|
| country | str | 目标国家 |
| visa_type | str | 签证类型 |
| intent | str | 用户意图分类 |
| missing_slots | List[str] | 缺失的必填信息槽位（**只由 slot_filling 写入**，决定是否追问） |
| required_materials | List[str] | material 意图检索到的所需材料清单（仅供回复引用，**不决定流程**） |
| risk_level | str | 风险等级(low/medium/high) |
| order_id | str | 签证订单号 |
| flow_path | str | ask/confirm/normal/handoff/chitchat |
| need_confirm | bool | 中风险是否需用户确认 |
| confirm_prompt | str | 确认问句 |

> **`missing_slots` 与 `required_materials` 必须分开**：前者是"还缺用户什么信息"（触发追问），
> 后者是"这类签证通常要什么材料"（给模型参考）。两者曾共用一个字段，导致用户问
> "日本旅游签证要什么材料"时材料清单被当成"还缺信息"，路由成 ask，用户拿不到答案。

## 对外输出（GraphOutput）
`final_reply` / `need_handoff` / `handoff_reason` / `intent` / `risk_level` / `flow_path`

> `flow_path` 必须保留：H5（`h5/assets/app.js`）用它渲染路径标签与 confirm/handoff 样式，
> 线上评测也用它验证路由。字段一旦从 `GraphOutput` 移除，前端会静默拿到 undefined。

## 知识库检索

- 实现：`utils/knowledge.py`（本地 Markdown 关键词检索，无外部依赖）
- **国别门控**：`search(required_terms=[country])`。用户指明的国家必须真的出现在文档节里，
  该节才允许参与打分；不满足的章节在打分前就被排除。
  节点在 `country` 非空时传入该参数。
  - 为什么必要：打分只看关键词重合，"火星签证"里的"签证""材料"会命中**别国**章节，
    系统会拿日本资料回答火星问题。门控让"不编造"由结构保证。
  - 别名归一化：`COUNTRY_ALIASES` 处理口语简称（美签→美国）与申根成员国（法国→申根）。
    查询串与门控术语共用同一套归一化，且长别名优先替换。
    注意：爱尔兰不是申根国、英国有独立体系，**不得**映射到申根。
- 知识库当前覆盖 9 个：日本、韩国、泰国、美国、英国、澳大利亚、申根、新加坡、加拿大。
  其余国家检索结果为零依据（这是期望行为，不是缺陷）。

## 风险关键词的适用范围
`risk_assessment_node` **只扫描用户消息**，不扫描 `knowledge_context`。
政策原文里天然含"拒签""自由职业"等字眼，那是文档在描述规则，不代表该用户存在风险；
曾因把知识库正文纳入扫描，导致正常提问被误判为高风险并转人工。

## 风险分档口径
- **高风险（转人工）**：遣返、非法滞留、造假、假材料、黑名单、敏感、军事、情报、政治、
  保证出签、包过、伪造 等——标准是"真实违规、失信或违规请求"。
- **中风险（加强提示 + 用户确认）**：自由职业、加急、存款不足、第一次出国、**拒签** 等。
- 「拒签」**不在高风险**：被拒签是常见且合法的再申请场景，一律转人工会淹没人工坐席。
  它曾同时出现在两个列表里且高风险优先，导致中风险的"之前拒签"永不生效；
  现已统一归入中风险。
- **配置一致性由测试保证**（`tests/test_risk_keyword_config.py`）：两个列表之间
  不允许同词，也不允许子串遮蔽（风险匹配是"先扫高风险、命中即停"，
  较短的关键词会遮蔽较长的，被遮蔽的那条就是死代码）。
  新增关键词时若违反该约束，CI 会失败。

## 测试与评测
- 单元/契约测试：`projects/tests/`（离线，无需 API Key），见 `tests/README.md`
- 金标评测：`projects/eval/`，见 `eval/README.md`
  - `python eval/run.py --mode offline`（CI 用，无需密钥）
  - `python eval/run.py --mode live`（需 `DEEPSEEK_API_KEY`，会产生费用）
- CI：`.github/workflows/tests.yml`（compileall + pytest + 离线评测门禁）


## LLM 配置
- 模型：DeepSeek 直连（`utils/llm.py`，基于 langchain-openai ChatOpenAI）
- 环境变量：`DEEPSEEK_API_KEY`（必填），`DEEPSEEK_BASE_URL`（可选，默认 https://api.deepseek.com）
- 模型名在 `config/*.json` 的 `config.model` 字段配置（默认 `deepseek-chat`）
- 无 Coze 平台依赖：知识库检索、异步任务、OpenAI 兼容接口均为本地实现
