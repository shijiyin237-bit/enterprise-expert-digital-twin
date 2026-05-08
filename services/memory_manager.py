"""
企业级知识检索中枢 - Enterprise Knowledge Retriever
实现基于业务意图的企业知识切片精准召回
"""

import os
from dotenv import load_dotenv
from typing import List
# [核心节点]：对接企业级数据契约
from domain.models import KnowledgeChunk, ProbeState

# 加载环境变量
load_dotenv()

# [核心节点]：B 端企业级命名规范
CLIENT_NAME = os.getenv("CLIENT_NAME", "客户")
EXPERT_NAME = os.getenv("EXPERT_NAME", "专家")


class AdvancedRetriever:
    """
    企业级知识检索器
    基于业务意图从企业知识库中检索最相关的知识切片
    """

    def __init__(self):
        """初始化高级检索器"""
        pass

    def get_contextual_knowledge(
        self,
        probe_state: ProbeState,
        knowledge_base: List[KnowledgeChunk],
        top_k: int = 3
    ) -> List[KnowledgeChunk]:
        """
        [核心节点]：基于业务意图检索最相关的企业知识切片
        
        输入：探针状态（包含业务意图和紧急程度）、企业知识库、返回数量
        输出：最相关的知识切片列表
        副作用：无
        
        原理：根据业务意图与知识切片类型的匹配度进行加权评分
        """
        # [核心节点]：计算每个知识切片的相关性分数
        scored_chunks = []
        
        for chunk in knowledge_base:
            score = self._calculate_relevance_score(probe_state, chunk)
            scored_chunks.append((score, chunk))
        
        # 按分数降序排序
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        
        # 返回 top_k 个最相关的切片
        top_chunks = [chunk for score, chunk in scored_chunks[:top_k]]
        
        return top_chunks

    def _calculate_relevance_score(
        self,
        probe_state: ProbeState,
        chunk: KnowledgeChunk
    ) -> float:
        """
        [核心节点]：计算知识切片与业务意图的相关性分数
        
        输入：探针状态、知识切片
        输出：相关性分数（0-1之间）
        副作用：无
        
        原理：根据业务意图与切片类型的匹配度进行加权评分
        """
        score = 0.0
        
        # [核心节点]：业务意图与切片类型匹配分数（权重 0.8）
        intent_match = self._match_intent(probe_state.business_intent, chunk.chunk_type)
        score += intent_match * 0.8
        
        # 紧急程度加成（权重 0.2）
        # 高紧急度时优先 SOP 类型切片
        if probe_state.urgency_level == "P0-紧急" and chunk.chunk_type == "SOP_STEP":
            score += 0.2
        elif probe_state.urgency_level == "P1-高优" and chunk.chunk_type in ["SOP_STEP", "BUSINESS_RULE"]:
            score += 0.15
        
        return score

    def _match_intent(self, business_intent: str, chunk_type: str) -> float:
        """
        [核心节点]：企业级业务意图与知识切片类型匹配
        
        输入：探针检测的业务意图、知识切片类型
        输出：匹配分数（0-1之间，CHIT_CHAT 直接返回 0.1 阻断 RAG）
        副作用：无
        
        原理：B 端企业场景根据业务意图优先召回特定类型的知识切片
        """
        # [核心节点]：CHIT_CHAT 直接阻断 RAG - B 端企业系统闲聊不需要知识支撑
        if business_intent == "CHIT_CHAT":
            return 0.1
        
        # [核心节点]：企业级业务意图与切片类型映射表
        # 映射逻辑：TECHNICAL_SUPPORT 优先给 SOP流程/产品参数，SALES_PITCH 优先给 话术话术/产品参数
        if business_intent == "TECHNICAL_SUPPORT":
            if chunk_type == "SOP_STEP":
                return 1.0
            elif chunk_type == "QA_PAIR":
                return 0.8
            elif chunk_type == "BUSINESS_RULE":
                return 0.7
            else:
                return 0.3
        
        elif business_intent == "SALES_PITCH":
            if chunk_type == "QA_PAIR":
                return 1.0
            elif chunk_type == "BUSINESS_RULE":
                return 0.6
            else:
                return 0.3
        
        elif business_intent == "COMPLAINT":
            if chunk_type == "SOP_STEP":
                return 0.9  # 投诉处理需要标准流程
            elif chunk_type == "BUSINESS_RULE":
                return 0.8  # 业务红线不能触碰
            else:
                return 0.4
        
        elif business_intent == "URGENT_ESCALATION":
            if chunk_type == "SOP_STEP":
                return 1.0  # 紧急升级必须按流程
            elif chunk_type == "BUSINESS_RULE":
                return 0.9  # 红线优先级高
            else:
                return 0.5
        
        # 默认匹配分数
        return 0.4

    def _match_scenario(self, business_intent: str, chunk_content: str) -> float:
        """
        [核心节点]：企业级场景匹配（辅助评分维度）
        
        输入：业务意图、知识切片内容
        输出：匹配分数（0-1之间）
        副作用：无
        
        原理：基于内容关键词进行辅助匹配
        """
        # [核心节点]：企业级关键词映射
        keyword_mapping = {
            "TECHNICAL_SUPPORT": ["错误", "异常", "故障", "报错", "无法", "失败", "日志", "排查"],
            "SALES_PITCH": ["价格", "报价", "方案", "产品", "功能", "优势", "对比"],
            "COMPLAINT": ["不满", "投诉", "退款", "赔偿", "解决", "处理", "道歉"],
            "URGENT_ESCALATION": ["紧急", "升级", "负责人", "主管", "经理", "总监"],
            "CHIT_CHAT": ["你好", "谢谢", "再见", "在吗"]  # 闲聊关键词，低分
        }
        
        # 获取业务意图对应的关键词列表
        keywords = keyword_mapping.get(business_intent, [])
        
        # 统计匹配的关键词数量
        match_count = sum(1 for kw in keywords if kw in chunk_content)
        
        # 基于匹配数量计算分数
        if match_count >= 3:
            return 0.9
        elif match_count == 2:
            return 0.7
        elif match_count == 1:
            return 0.5
        
        # 不匹配
        return 0.2
