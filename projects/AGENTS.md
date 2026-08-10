## 项目概述
- **名称**: 签证客服助手-Demo
- **功能**: 签证咨询与材料引导工作流，支持意图分类、知识库检索、槽位填充、风险评估、订单进度查询，输出结构化回复

### 节点清单
| 节点名 | 文件位置 | 类型 | 功能描述 | 分支逻辑 | 配置文件 |
|-------|---------|------|---------|---------|---------|
| intent_classify | `nodes/intent_classify_node.py` | agent | LLM意图分类，提取国家/签证类型/订单号 | - | `config/intent_classify_llm_cfg.json` |
| knowledge_retrieval | `nodes/knowledge_retrieval_node.py` | task | 知识库语义检索签证信息 | - | - |
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
- 数据集名称: `visa_knowledge`
- 文档: `assets/countries_faq.md`（各国签证FAQ）
- 文档: `assets/material_checklist.md`（签证材料清单）
- 文档: `assets/risk_policy.md`（风险评估政策）

## 会话状态变量
| 变量名 | 类型 | 说明 |
|-------|------|------|
| country | str | 目标国家 |
| visa_type | str | 签证类型 |
| intent | str | 用户意图分类 |
| missing_slots | List[str] | 缺失的必填信息槽位 |
| risk_level | str | 风险等级(low/medium/high) |
| order_id | str | 签证订单号 |
| flow_path | str | ask/confirm/normal/handoff/chitchat |
| need_confirm | bool | 中风险是否需用户确认 |
| confirm_prompt | str | 确认问句 |

## 技能使用
- 节点`intent_classify`使用大语言模型（意图分类）
- 节点`knowledge_retrieval`使用知识库（语义检索）
- 节点`slot_filling`使用大语言模型（槽位填充）
- 节点`response_generate`使用大语言模型（回复生成）
