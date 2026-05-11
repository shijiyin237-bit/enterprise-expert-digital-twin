"""
领域模型 - Domain Models
企业级专家数字孪生系统核心数据契约
使用 Pydantic V2 构建防腐层，所有模型都经过严格校验，防止大模型幻觉污染
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
import re


class ChunkType(str, Enum):
    """
    知识切片类型枚举
    
    用途：标识企业知识切片的类型
    """
    QA_PAIR = "QA_PAIR"
    SOP_STEP = "SOP_STEP"
    BUSINESS_RULE = "BUSINESS_RULE"


class UrgencyLevel(str, Enum):
    """
    紧急程度枚举
    
    用途：标识用户请求的紧急程度，用于优先级路由
    """
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class DigitalTwinProfile(BaseModel):
    """
    数字孪生专家画像模型
    
    输入：从配置文件或大模型侧写输出的原始 JSON 数据
    输出：经过 Pydantic 校验和清洗后的结构化专家画像对象
    副作用：自动清洗大模型生成的解释性废话，确保数据纯净
    
    用途：存储企业数字孪生专家的完整画像，包括专业领域、沟通风格、业务红线等
    
    [核心节点]：多租户专家池架构 - 每个专家拥有全局唯一的 expert_id
    """
    expert_id: str = Field(..., description="专家全局唯一标识（拼音或UUID）", examples=["jinpaifuwu_001", "zhuanjia_abc123"])
    expert_name: str = Field(..., description="专家姓名/代号", examples=["金牌架构师", "资深法务", "售前金牌销售"])
    domain_expertise: str = Field(..., description="专业领域", examples=["云计算架构", "企业法律合规", "售前咨询"])
    communication_style: Dict[str, Any] = Field(
        default_factory=dict,
        description="沟通风格描述（从原有的 language_features 演变而来），包含专家在业务中高频使用的金牌话术模板/口头禅",
        examples=[
            {
                "tone": "专业严谨", 
                "avg_response_length": 50, 
                "preferred_greeting": "您好",
                "standard_scripts": ["建议您尽快带孩子去医院做进一步检查", "这款目前库存紧张，建议先拍下锁单"]
            }
        ]
    )
    business_redlines: List[str] = Field(
        default_factory=list,
        description="业务红线（禁止触碰的边界）",
        examples=["绝不承诺未发布的特性", "不得泄露客户敏感数据", "禁止提供未经授权的技术访问"]
    )
    golden_few_shots: List[Dict[str, str]] = Field(
        default_factory=list,
        description="金牌示例对话，用于大模型 Few-Shot 模仿",
        examples=[[{"user_input": "...", "expert_reply": "..."}]]
    )
    supported_intents: List[str] = Field(
        default_factory=list,
        description="专家支持的专属业务意图列表（如：病理问诊、用药指导、闲聊兜底）",
        examples=[["病理问诊", "用药指导", "闲聊兜底"]]
    )
    
    @field_validator('supported_intents')
    @classmethod
    def validate_supported_intents(cls, v: List[str]) -> List[str]:
        """
        租户专属意图列表验证
        
        输入：原始意图列表
        输出：验证后的意图列表
        副作用：无
        
        原理：确保意图列表至少包含3个意图，且必须包含兜底意图
        """
        if len(v) < 3:
            raise ValueError(f"专家必须支持至少3个业务意图，当前仅有 {len(v)} 个: {v}")
        
        # 检查是否包含兜底意图
        fallback_keywords = ['兜底', '其他', '闲聊', '杂项', '通用', '默认', 'misc', 'other', 'general']
        has_fallback = any(
            any(keyword in intent.lower() for keyword in fallback_keywords)
            for intent in v
        )
        
        if not has_fallback:
            raise ValueError(f"专家意图列表必须包含兜底意图（如：闲聊兜底、其他咨询等），当前列表: {v}")
        
        return [intent.strip() for intent in v if intent.strip()]
    
    @field_validator('expert_name', 'domain_expertise')
    @classmethod
    def clean_llm_fluff(cls, v: str) -> str:
        """
        反 LLM 谄媚机制：清洗大模型输出的解释性废话
        
        输入：可能包含废话前缀的原始文本（如"从对话中可以看出..."）
        输出：去除废话后的纯设定文本
        副作用：无
        
        原理：使用正则表达式匹配并删除常见的 LLM 废话模式
        """
        # [核心节点]：此处利用正则表达式物理斩断大模型生成的废话前缀
        fluff_patterns = [
            r'从对话中可以看出[，,]?\s*',
            r'根据语料分析[，,]?\s*',
            r'该专家表现出[，,]?\s*',
            r'从上述对话可以得出[，,]?\s*',
            r'基于对话内容[，,]?\s*',
            r'作为一个AI[，,]?\s*',
            r'经过分析[，,]?\s*',
            r'可以看出[，,]?\s*',
            r'显示出[，,]?\s*',
            r'表现出[，,]?\s*',
        ]
        
        cleaned = v
        for pattern in fluff_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # 去除首尾空白
        cleaned = cleaned.strip()
        
        return cleaned
    
    @field_validator('business_redlines')
    @classmethod
    def clean_list_items(cls, v: List[str]) -> List[str]:
        """
        列表字段验证和清洗
        
        输入：原始的列表数据
        输出：去除空白和空字符串后的列表
        副作用：无
        
        原理：防止大模型输出格式错误导致后续处理崩溃
        """
        # [核心节点]：此处确保列表项都是非空字符串
        return [item.strip() for item in v if item.strip()]


class KnowledgeChunk(BaseModel):
    """
    企业知识切片模型
    
    输入：从企业知识库中提取的单条知识数据
    输出：标准化的知识切片对象
    副作用：无
    
    用途：存储企业知识库的单条记录，包括内容、类型和来源出处
    
    [核心节点]：多租户专家池架构 - 每个知识切片关联到特定专家
    """
    content: str = Field(..., description="切片内容", examples=["API接口调用失败时，请检查认证token是否过期"])
    expert_id: str = Field(..., description="所属专家的全局唯一标识", examples=["jinpaifuwu_001"])
    chunk_type: Literal["QA_PAIR", "SOP_STEP", "BUSINESS_RULE"] = Field(
        ...,
        description="切片类型（必须是枚举值之一）",
        examples=["QA_PAIR", "SOP_STEP", "BUSINESS_RULE"]
    )
    citation_source: str = Field(..., description="必须包含来源出处，防幻觉", examples=["技术文档v2.3", "销售话术手册", "产品规格表"])
    
    @field_validator('content', 'citation_source')
    @classmethod
    def clean_text_fields(cls, v: str) -> str:
        """
        文本字段验证和清洗
        
        输入：原始的文本数据
        输出：去除首尾空白后的文本
        副作用：无
        
        原理：防止大模型输出格式错误导致后续处理崩溃
        """
        # [核心节点]：此处确保文本字段去除首尾空白
        return v.strip()


class ProbeState(BaseModel):
    """
    探针状态模型
    
    输入：意图识别探针输出的业务意图和紧急程度数据
    输出：经过 Pydantic 强校验后的探针状态对象
    副作用：无
    
    用途：捕获当前用户的业务意图和紧急程度，用于专家模型路由决策
    """
    business_intent: str = Field(
        ...,
        description="业务意图类型（租户专属动态意图，由专家画像定义）",
        examples=["病理问诊", "用药指导", "技术排障", "闲聊兜底"]
    )
    urgency_level: Literal["高", "中", "低"] = Field(
        ...,
        description="紧急程度（必须是枚举值之一）",
        examples=["高", "中", "低"]
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="分类置信度（0-1之间）",
        examples=[0.95, 0.87, 0.72]
    )
