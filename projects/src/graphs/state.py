"""签证客服助手-Demo - 状态定义（v2：风控全链路覆盖 + 5类意图）"""
from typing import Optional, List
from pydantic import BaseModel, Field


class GlobalState(BaseModel):
    """全局状态定义 - 工作流运行过程中的所有会话状态"""
    user_message: str = Field(default="", description="用户原始消息")
    country: str = Field(default="", description="目标国家")
    visa_type: str = Field(default="", description="签证类型")
    intent: str = Field(default="", description="用户意图: faq/material/progress/complaint/chitchat")
    missing_slots: List[str] = Field(default=[], description="缺失的必填信息槽位（决定是否追问，只由 slot_filling 写入）")
    required_materials: List[str] = Field(
        default=[],
        description="material意图检索到的所需材料清单（只用于展示给模型，不决定流程）",
    )
    risk_level: str = Field(default="low", description="风险等级: low/medium/high")
    order_id: str = Field(default="", description="签证订单号")
    handoff_reason: str = Field(default="", description="转人工原因，为空表示无需转人工")
    knowledge_context: str = Field(default="", description="知识库检索到的上下文信息")
    order_status: str = Field(default="", description="订单进度查询结果")
    risk_advice: str = Field(default="", description="风险评估建议")
    final_reply: str = Field(default="", description="最终回复内容")
    need_handoff: bool = Field(default=False, description="是否需要转人工")
    need_confirm: bool = Field(default=False, description="中风险是否需用户确认后再继续")
    confirm_prompt: str = Field(default="", description="需用户确认时的草案/确认问句")
    flow_path: str = Field(
        default="",
        description="当前流程路径: ask/confirm/normal/handoff/chitchat"
    )
    slot_follow_up: str = Field(default="", description="槽位追问话术")
    complaint_summary: str = Field(default="", description="投诉摘要")
    order_follow_up: str = Field(default="", description="订单号追问/校验提示")
    order_valid: bool = Field(default=False, description="订单号是否通过验证")


class GraphInput(BaseModel):
    """工作流的输入"""
    user_message: str = Field(..., description="用户发送的消息内容")


class GraphOutput(BaseModel):
    """工作流的输出。

    注意：这里是图对外的**唯一**出口，不在其中的状态字段会被 LangGraph 裁掉。
    新增字段前先想清楚"外部谁在依赖它"——漏掉字段不会报错，只会让前端或评测
    静默拿到 undefined（flow_path 就曾经被漏掉，导致前端路径标签成为死代码）。
    """
    final_reply: str = Field(..., description="给用户的最终回复内容")
    need_handoff: bool = Field(default=False, description="是否需要转人工客服")
    handoff_reason: str = Field(default="", description="转人工原因")
    intent: str = Field(default="", description="识别到的用户意图")
    risk_level: str = Field(default="low", description="风险评估等级")
    # flow_path 必须对外暴露：H5 用它渲染"路径"标签与 confirm/handoff 样式，
    # 线上评测也用它验证路由是否走对（仅靠回复文本猜路径不可靠）。
    flow_path: str = Field(
        default="",
        description="流程路径: ask/confirm/normal/handoff/chitchat",
    )


# ========== 意图分类节点 ==========

class IntentClassifyInput(BaseModel):
    """意图分类节点的输入"""
    user_message: str = Field(..., description="用户原始消息")


class IntentClassifyOutput(BaseModel):
    """意图分类节点的输出"""
    intent: str = Field(..., description="识别的意图: faq/material/progress/complaint/chitchat")
    country: str = Field(default="", description="从消息中提取的目标国家")
    visa_type: str = Field(default="", description="从消息中提取的签证类型")
    order_id: str = Field(default="", description="从消息中提取的订单号")
    # 闲聊直达回复生成时跳过风控，需在此写入路径
    flow_path: str = Field(default="", description="闲聊时为 chitchat，其它意图留空由风控赋值")


# ========== 投诉转人工节点 ==========

class ComplaintHandoffInput(BaseModel):
    """投诉转人工节点的输入"""
    user_message: str = Field(..., description="用户原始消息")
    intent: str = Field(default="", description="用户意图")
    country: str = Field(default="", description="目标国家")


class ComplaintHandoffOutput(BaseModel):
    """投诉转人工节点的输出"""
    need_handoff: bool = Field(..., description="是否需要转人工")
    handoff_reason: str = Field(..., description="转人工原因")
    complaint_summary: str = Field(..., description="投诉摘要（意图+国家+原因）")
    flow_path: str = Field(default="handoff", description="流程路径标记")


# ========== 订单号验证节点 ==========

class OrderValidateInput(BaseModel):
    """订单号验证节点的输入"""
    order_id: str = Field(default="", description="从用户消息中提取的订单号")
    user_message: str = Field(default="", description="用户原始消息")


class OrderValidateOutput(BaseModel):
    """订单号验证节点的输出"""
    order_id: str = Field(default="", description="验证后的订单号")
    order_valid: bool = Field(..., description="订单号是否有效")
    order_follow_up: str = Field(default="", description="追问或校验提示话术")


# ========== 槽位填充节点 ==========

class SlotFillingInput(BaseModel):
    """槽位填充节点的输入"""
    user_message: str = Field(..., description="用户原始消息")
    intent: str = Field(..., description="用户意图")
    country: str = Field(default="", description="已提取的国家")
    visa_type: str = Field(default="", description="已提取的签证类型")


class SlotFillingOutput(BaseModel):
    """槽位填充节点的输出"""
    country: str = Field(default="", description="补充后的国家信息")
    visa_type: str = Field(default="", description="补充后的签证类型")
    missing_slots: List[str] = Field(default=[], description="仍缺失的必填槽位或所需材料列表")
    slot_follow_up: str = Field(default="", description="追问话术")


# ========== 知识库检索节点 ==========

class KnowledgeRetrievalInput(BaseModel):
    """知识库检索节点的输入"""
    country: str = Field(default="", description="目标国家")
    visa_type: str = Field(default="", description="签证类型")
    intent: str = Field(default="", description="用户意图")
    user_message: str = Field(default="", description="用户原始消息")


class KnowledgeRetrievalOutput(BaseModel):
    """知识库检索节点的输出。

    注意：这里刻意**不叫** missing_slots。
    "缺失的必填槽位"决定流程是否追问（ask），而"所需材料清单"只是给模型看的参考资料。
    两者曾经共用一个字段，导致用户问"日本旅游签证要什么材料"时，材料清单被当成
    "还缺信息"从而路由成 ask，用户拿不到答案。语义必须分开。
    """

    knowledge_context: str = Field(..., description="从知识库检索到的相关信息")
    required_materials: List[str] = Field(default=[], description="material意图：该签证类型的所需材料清单")


# ========== 风险门控节点 ==========

class RiskAssessmentInput(BaseModel):
    """风险评估节点的输入"""
    user_message: str = Field(default="", description="用户原始消息")
    intent: str = Field(default="", description="用户意图")
    country: str = Field(default="", description="目标国家")
    visa_type: str = Field(default="", description="签证类型")
    knowledge_context: str = Field(default="", description="知识库上下文")
    missing_slots: List[str] = Field(default=[], description="缺失槽位或材料")
    slot_follow_up: str = Field(default="", description="槽位追问话术")
    order_follow_up: str = Field(default="", description="订单号追问提示")
    need_handoff: bool = Field(default=False, description="上游是否已标记转人工")
    handoff_reason: str = Field(default="", description="上游转人工原因")


class RiskAssessmentOutput(BaseModel):
    """风险评估节点的输出"""
    risk_level: str = Field(..., description="风险等级: low/medium/high")
    risk_advice: str = Field(default="", description="风险评估建议")
    need_handoff: bool = Field(default=False, description="是否需要转人工")
    handoff_reason: str = Field(default="", description="转人工原因")
    need_confirm: bool = Field(default=False, description="中风险是否需用户确认")
    confirm_prompt: str = Field(default="", description="确认问句/草案")
    flow_path: str = Field(
        default="normal",
        description="ask/confirm/normal/handoff"
    )


# ========== 订单进度查询节点 ==========

class OrderProgressInput(BaseModel):
    """订单进度查询节点的输入"""
    order_id: str = Field(..., description="已验证的签证订单号")


class OrderProgressOutput(BaseModel):
    """订单进度查询节点的输出"""
    order_status: str = Field(..., description="订单当前状态描述")


# ========== 回复生成节点 ==========

class ResponseGenerateInput(BaseModel):
    """回复生成节点的输入"""
    user_message: str = Field(..., description="用户原始消息")
    intent: str = Field(..., description="用户意图")
    country: str = Field(default="", description="目标国家")
    visa_type: str = Field(default="", description="签证类型")
    knowledge_context: str = Field(default="", description="知识库上下文")
    order_status: str = Field(default="", description="订单状态")
    risk_level: str = Field(default="low", description="风险等级")
    risk_advice: str = Field(default="", description="风险建议")
    missing_slots: List[str] = Field(default=[], description="缺失槽位或所需材料")
    required_materials: List[str] = Field(default=[], description="material意图：所需材料清单")
    slot_follow_up: str = Field(default="", description="槽位追问话术")
    need_handoff: bool = Field(default=False, description="是否需要转人工")
    handoff_reason: str = Field(default="", description="转人工原因")
    need_confirm: bool = Field(default=False, description="是否需用户确认")
    confirm_prompt: str = Field(default="", description="确认草案问句")
    flow_path: str = Field(
        default="normal",
        description="流程路径: ask/confirm/normal/handoff/chitchat"
    )
    complaint_summary: str = Field(default="", description="投诉摘要")
    order_follow_up: str = Field(default="", description="订单号追问提示")


class ResponseGenerateOutput(BaseModel):
    """回复生成节点的输出"""
    final_reply: str = Field(..., description="最终回复内容")
