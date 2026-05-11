# 📋 企业级专家数字孪生中台 - 项目快照
**生成时间**: 2026-05-09 15:51:39
**项目路径**: A:\Windsurf_project\AI identify2.0企业版

## 📂 项目目录结构
```
📁 项目目录树结构 (.py/.md 仅显示):
├── api_gateway.py
├── domain
│   └── models.py
├── engineering_norms.md
├── generate_snapshot.py
├── main_router_test.py
├── README.md
├── services
│   ├── agent_engine.py
│   ├── etl_pipeline.py
│   ├── expert_manager.py
│   ├── memory_manager.py
│   ├── state_tracker.py
│   └── vector_db_service.py
├── start_system.py
├── tools
│   ├── local_corpus_parser.py
│   └── universal_ingestor.py
└── web_ui.py
```

## 🔧 核心文件源代码
### 📄 domain/models.py
```python
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
        description="沟通风格描述（从原有的 language_features 演变而来）",
        examples=[{"tone": "专业严谨", "avg_response_length": 50, "preferred_greeting": "您好"}]
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

```

### 📄 api_gateway.py
```python
"""
FastAPI 统一网关 - Project 6.0 Persona Engine
对外提供 RESTful API 接口，内部调用 PersonaAgent 生成回复
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
import uvicorn
import os
import sys
import json
import traceback
from datetime import datetime

from services.agent_engine import ExpertDigitalTwinAgent
import glob

# [核心节点]：动态加载默认专家ID（多租户架构）
def get_default_expert_id() -> str:
    """
    从 data/experts/ 目录读取第一个专家ID作为默认启动专家
    
    输出：专家ID字符串
    异常：如果目录为空，返回None
    """
    experts_dir = os.path.join(os.path.dirname(__file__), "data", "experts")
    
    if not os.path.exists(experts_dir):
        return None
    
    # 获取所有子目录（专家目录）
    expert_dirs = [d for d in os.listdir(experts_dir) 
                   if os.path.isdir(os.path.join(experts_dir, d))]
    
    # 过滤掉空目录，优先选择非空目录
    valid_experts = []
    for expert_id in expert_dirs:
        expert_path = os.path.join(experts_dir, expert_id)
        if os.listdir(expert_path):  # 目录非空
            valid_experts.append(expert_id)
    
    if not valid_experts:
        return None
    
    # 返回第一个有效的专家ID
    return valid_experts[0]

# 确保日志目录存在
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "system_trace.log")

def write_system_trace(user_input: str, business_intent: str, urgency_level: str, retrieved_memories: List[str], reply: str, generation_time: float, prompt_length: int, temperature: float):
    """
    写入系统追踪日志
    
    输入：用户输入、业务意图、紧急程度、RAG记忆、回复、耗时、Prompt长度、温度
    输出：无
    副作用：追加写入日志文件
    
    原理：将本次对话的关键信息以 JSONL 格式写入日志文件，用于业务意图追踪和紧急事件审计
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "user_input": user_input,
        "business_intent": business_intent,
        "urgency_level": urgency_level,
        "retrieved_memories": retrieved_memories,
        "reply": reply,
        "generation_time": generation_time,
        "prompt_length": prompt_length,
        "temperature": temperature
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


# Pydantic 契约定义
class ChatRequest(BaseModel):
    """企业级对话请求契约"""
    user_query: str = Field(
        ...,
        description="企业客户的业务咨询或技术报障，将经过业务意图探针分析后路由至对应专家生成回复",
        examples=["服务器一直报 502 错误怎么排查？", "请问企业版 API 额度如何计费？", "你好，我想咨询一下产品功能"]
    )
    session_history: List[dict] = Field(
        default_factory=list,
        description="当前会话的短期上下文历史，格式为 [{'role': 'user/assistant', 'content': '...'}]",
        examples=[[{"role": "user", "content": "你好"}, {"role": "assistant", "content": "您好，有什么可以帮助您？"}]]
    )
    temperature: float = Field(
        default=0.7,
        description="大模型发散温度，控制回复的确定性。B 端场景建议低温度以确保准确性",
        examples=[0.7]
    )
    frequency_penalty: float = Field(
        default=0.2,
        description="防复读惩罚，降低重复内容的概率",
        examples=[0.2]
    )
    presence_penalty: float = Field(
        default=0.2,
        description="新话题激励，鼓励模型讨论新话题",
        examples=[0.2]
    )
    max_tokens: int = Field(
        default=500,
        description="最大生成 Token 数，企业级回复可能需要更详细的解释",
        examples=[500]
    )
    stop_sequences: List[str] = Field(
        default_factory=lambda: ["\nCustomer:", "\nExpert:"],
        description="停止序列，防止模型生成对话双方内容",
        examples=[["\nCustomer:", "\nExpert:"]]
    )


class ChatResponse(BaseModel):
    """企业级对话响应契约"""
    reply: str = Field(
        ...,
        description="专家生成的专业回复文本，基于业务意图探针和知识切片动态生成",
        examples=["请检查 Nginx 错误日志，502 错误通常表示后端服务不可用", "企业版 API 按调用次数计费，详情如下...", "您好，请问有什么可以帮助您？"]
    )
    business_intent: str = Field(
        ...,
        description="业务意图探针识别结果：TECHNICAL_SUPPORT(技术支持)、SALES_PITCH(销售咨询)、CHIT_CHAT(闲聊兜底)",
        examples=["TECHNICAL_SUPPORT", "SALES_PITCH", "CHIT_CHAT"]
    )
    urgency_level: str = Field(
        ...,
        description="紧急程度判定结果：高(系统故障/业务中断)、中(功能异常)、低(一般咨询)",
        examples=["高", "中", "低"]
    )
    retrieved_memories: list = Field(
        default_factory=list,
        description="RAG 召回的企业级知识切片文本，用于 CTO 白盒监控",
        examples=[["Q: 502 错误如何排查？A: 检查后端服务状态..."]]
    )
    prompt_length: int = Field(
        default=0,
        description="最终组装发给大模型的 Token/字符长度，用于算力消耗监控",
        examples=[2000]
    )
    generation_time: float = Field(
        default=0.0,
        description="大模型推理耗时（秒），用于性能监控",
        examples=[1.5]
    )


class SwitchExpertRequest(BaseModel):
    """切换专家请求契约"""
    expert_id: str = Field(
        ...,
        description="目标专家的唯一标识符",
        examples=["expert_20260508_183912", "zhuanjia_20260507_165342"]
    )


class SwitchExpertResponse(BaseModel):
    """切换专家响应契约"""
    success: bool = Field(
        ...,
        description="切换是否成功",
        examples=[True, False]
    )
    message: str = Field(
        ...,
        description="切换结果消息",
        examples=["专家切换成功", "专家不存在"]
    )
    expert_name: str = Field(
        default="",
        description="当前激活的专家名称",
        examples=["金牌架构师", "资深法务"]
    )


# [核心节点]：初始化 FastAPI 企业级网关
app = FastAPI(
    title="企业级专家数字孪生系统网关",
    description="B 端企业级专家数字孪生对话系统 - 基于业务意图探针与企业知识切片",
    version="1.0.0"
)

# [核心节点]：初始化全局 ExpertDigitalTwinAgent 实例（多租户架构）
print("[系统点火] 正在探测已炼丹的专家数据...")
default_expert_id = get_default_expert_id()

if not default_expert_id:
    print("[错误] 未找到任何已炼丹的专家数据，请先运行 etl_pipeline.py")
    print("[提示] 运行命令: python services/etl_pipeline.py")
    sys.exit(1)

print(f"[系统点火] 正在加载默认专家: {default_expert_id}")
try:
    agent = ExpertDigitalTwinAgent(expert_id=default_expert_id)
    print(f"[系统点火] 专家 [{agent.expert_profile.expert_name}] 加载完成，系统准备就绪\n")
except Exception as e:
    print(f"[致命错误] 专家加载失败: {e}")
    sys.exit(1)

# [物理切除]：SillyTavern 适配器已物理删除
# B 端企业系统不需要酒馆角色卡导出功能


@app.get(
    "/",
    summary="服务根路径",
    description="返回服务基本信息，用于快速确认服务是否正常运行",
    tags=["系统状态接口"]
)
async def root():
    """根路径 - 健康检查"""
    return {
        "service": "企业级专家数字孪生系统网关",
        "status": "running",
        "version": "1.0.0"
    }


@app.get(
    "/health",
    summary="健康检查",
    description="检查服务健康状态，返回专家名称和知识库大小等关键指标",
    tags=["系统状态接口"]
)
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "expert_name": agent.expert_profile.expert_name,
        "knowledge_base_size": len(agent.knowledge_base)
    }


@app.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    summary="发送聊天请求",
    description="接收用户输入，经过业务意图探针分析与知识切片召回，返回企业级专家回复。系统会自动识别用户业务意图和紧急程度，从企业知识库中检索最相关的知识切片，并基于专家画像规则生成专业回复。",
    tags=["核心对话接口"]
)
async def chat(request: ChatRequest):
    """
    聊天接口 - 接收用户输入，生成企业级专家回复
    
    Args:
        request: 包含 user_query 的请求体
        
    Returns:
        ChatResponse: 包含回复、业务意图和紧急程度的响应
    """
    try:
        print(f"\n[API] 收到聊天请求: \"{request.user_query}\"")
        
        # [核心节点]：调用企业级专家数字孪生引擎生成回复
        result = agent.generate_reply(
            request.user_query,
            request.session_history,
            request.temperature,
            request.frequency_penalty,
            request.presence_penalty,
            request.max_tokens,
            request.stop_sequences
        )
        
        print(f"[API] 聊天请求处理完成")
        
        # [核心节点]：写入系统追踪日志
        write_system_trace(
            user_input=request.user_query,
            business_intent=result.get("business_intent", "CHIT_CHAT"),
            urgency_level=result.get("urgency_level", "低"),
            retrieved_memories=result.get("retrieved_memories", []),
            reply=result["reply"],
            generation_time=result.get("generation_time", 0.0),
            prompt_length=result.get("prompt_length", 0),
            temperature=request.temperature
        )
        
        return ChatResponse(
            reply=result["reply"],
            business_intent=result.get("business_intent", "CHIT_CHAT"),
            urgency_level=result.get("urgency_level", "低"),
            retrieved_memories=result.get("retrieved_memories", []),
            prompt_length=result.get("prompt_length", 0),
            generation_time=result.get("generation_time", 0.0)
        )
        
    except Exception as e:
        # [核心节点]：异常透传与 traceback 打印
        error_traceback = traceback.format_exc()
        print(f"[API] 处理请求时发生错误:")
        print(error_traceback)
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")


@app.post(
    "/api/v1/switch_expert",
    response_model=SwitchExpertResponse,
    summary="切换专家",
    description="动态切换当前激活的专家，无需重启服务。接收 expert_id 参数，重新初始化 ExpertDigitalTwinAgent。",
    tags=["多租户专家管理"]
)
async def switch_expert(request: SwitchExpertRequest):
    """
    切换专家接口 - 多租户架构核心功能
    
    允许指挥官在运行时切换不同专家（如从儿科切换到法律），无需重启服务。
    全局变量 agent 被重新赋值为新的 ExpertDigitalTwinAgent 实例。
    
    Args:
        request: 包含目标 expert_id 的请求体
        
    Returns:
        SwitchExpertResponse: 切换结果，包含成功状态和当前专家名称
    """
    global agent
    
    try:
        print(f"\n[多租户切换] 收到专家切换请求: {request.expert_id}")
        
        # 验证专家是否存在
        experts_dir = os.path.join(os.path.dirname(__file__), "data", "experts")
        target_expert_path = os.path.join(experts_dir, request.expert_id)
        
        if not os.path.exists(target_expert_path) or not os.listdir(target_expert_path):
            print(f"[多租户切换] 专家不存在或目录为空: {request.expert_id}")
            return SwitchExpertResponse(
                success=False,
                message=f"专家 '{request.expert_id}' 不存在或未完成炼丹，请检查 expert_id",
                expert_name=agent.expert_profile.expert_name if agent else ""
            )
        
        # [核心节点]：重新初始化全局 agent 实例
        print(f"[多租户切换] 正在加载新专家: {request.expert_id}")
        new_agent = ExpertDigitalTwinAgent(expert_id=request.expert_id)
        
        # 切换成功后才赋值给全局变量
        agent = new_agent
        
        print(f"[多租户切换] 专家切换成功！当前专家: [{agent.expert_profile.expert_name}]")
        
        return SwitchExpertResponse(
            success=True,
            message=f"专家切换成功，当前以【{agent.expert_profile.expert_name}】身份应答",
            expert_name=agent.expert_profile.expert_name
        )
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"[多租户切换] 切换失败:")
        print(error_traceback)
        return SwitchExpertResponse(
            success=False,
            message=f"专家切换失败: {str(e)}",
            expert_name=agent.expert_profile.expert_name if agent else ""
        )


if __name__ == "__main__":
    print("=" * 80)
    print("启动 FastAPI 企业级专家数字孪生网关")
    print("=" * 80)
    print(f"服务地址: http://0.0.0.0:8088")
    print(f"API 文档: http://0.0.0.0:8088/docs")
    print("=" * 80)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8088,
        log_level="info"
    )

```

### 📄 services/agent_engine.py
```python
"""
企业级专家数字孪生引擎 - Expert Digital Twin Agent
基于业务意图探针与企业知识切片的核心生成引擎
整合意图分诊、RAG 知识召回、大模型生成的完整链路

[核心节点]：多租户专家池架构 - 通过 expert_id 实现动态专家切换
"""

import os
import sys
import time
import json
from pathlib import Path
from typing import List, Optional, Dict
import openai
from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# [核心节点]：对接企业级数据契约
from domain.models import DigitalTwinProfile, KnowledgeChunk, ProbeState
from services.state_tracker import BusinessIntentProbe
from services.memory_manager import AdvancedRetriever
from services.vector_db_service import HybridSearchEngine
from services.expert_manager import ExpertManager, get_expert_manager


class ExpertDigitalTwinAgent:
    """
    企业级专家数字孪生智能体 - B 端核心生成引擎
    
    [核心节点]：多租户专家池架构 - 通过 expert_id 动态加载不同专家
    每个专家拥有独立的 Profile、KnowledgeBase 和 VectorDB 命名空间
    """
    
    def __init__(self, expert_id: str, api_key: str = None, base_url: str = None):
        """
        初始化企业级专家数字孪生智能体（多租户版本）
        
        输入：
            - expert_id: 专家唯一标识（租户隔离键，必须指定）
            - api_key: API 密钥（优先从环境变量读取）
            - base_url: API 基础 URL（优先从环境变量读取）
        输出：ExpertDigitalTwinAgent 实例
        副作用：初始化向量数据库、业务意图探针、大模型客户端
        
        原理：通过 ExpertManager 动态加载指定专家的数据，实现运行时专家切换
        
        [核心节点]：不再默认加载静态文件，而是根据 expert_id 动态加载
        """
        # 加载环境变量
        load_dotenv()
        
        # [核心节点]：必须指定 expert_id，多租户架构的核心
        if not expert_id:
            raise ValueError("致命错误：必须指定 expert_id！多租户专家池架构要求明确指定专家标识。")
        self.expert_id = expert_id
        
        print("=" * 60)
        print(f"[+] 正在初始化 ExpertDigitalTwinAgent")
        print(f"[+] 专家 ID: {expert_id}")
        print("=" * 60)
        
        # [核心节点]：使用 ExpertManager 动态加载指定专家的数据
        self.expert_manager = get_expert_manager()
        expert_data = self.expert_manager.load_expert(expert_id)
        
        if expert_data is None:
            raise ValueError(f"致命错误：专家 {expert_id} 不存在！请先运行 ETL 流程创建该专家。")
        
        self.expert_profile, self.knowledge_base = expert_data
        print(f"[+] 专家画像加载完成: {self.expert_profile.expert_name}")
        print(f"[!] 身份校准成功：正以【{self.expert_profile.expert_name}】专家人格进行应答")
        print(f"[+] 知识库加载完成: {len(self.knowledge_base)} 条企业知识切片")
        
        # [核心节点]：初始化业务意图探针（替代情绪探针）
        self.intent_probe = BusinessIntentProbe()
        print("[+] 业务意图探针初始化完成")
        
        # [核心节点]：此处初始化混合检索引擎，实现 Dense + Sparse + Reranking 三路召回
        try:
            self.vector_db = HybridSearchEngine()
            print("[+] 混合检索引擎初始化完成 (Dense + Sparse + Reranking)")
        except Exception as e:
            print(f"[!] 混合检索引擎初始化失败: {e}")
            print("[!] 将降级使用传统检索器")
            self.vector_db = None
            self.retriever = AdvancedRetriever()
            print("[+] 高级检索器初始化完成（降级模式）")
        
        # 初始化 OpenAI 客户端（从环境变量读取配置）
        api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        base_url = base_url or os.getenv("BASE_URL")
        
        # Fail Fast: 如果没有真实 API 密钥，直接抛出致命错误
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("致命错误：未检测到真实的 API 密钥！请检查 .env 文件中的 SILICONFLOW_API_KEY 是否已配置为真实密钥。")
        
        if not base_url:
            raise ValueError("致命错误：未检测到 BASE_URL！请检查 .env 文件中的 BASE_URL 是否已配置。")
        
        print(f"[系统调试] API 密钥已成功加载，长度为: {len(api_key)}")
        
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        print(f"[+] OpenAI 客户端初始化完成 (Base URL: {base_url})")
        
        print("[+] ExpertDigitalTwinAgent 初始化完成\n")
    
    def _load_expert_profile(self) -> DigitalTwinProfile:
        """
        [核心节点]：从本地加载专家数字孪生画像
        
        输入：无
        输出：DigitalTwinProfile 对象
        副作用：无
        
        原理：读取 data/digital_twin_profile.json 并反序列化为企业级专家画像
        """
        profile_path = Path("data/digital_twin_profile.json")
        if not profile_path.exists():
            print("[!] 警告: 未找到专家画像文件，使用默认配置")
            return DigitalTwinProfile(
                expert_name="默认专家",
                domain_expertise="通用咨询",
                communication_style={"tone": "专业严谨", "avg_response_length": 100},
                business_redlines=["绝不承诺未授权内容", "不得泄露敏感数据"]
            )
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return DigitalTwinProfile(**data)
    
    def _load_knowledge_base(self) -> List[KnowledgeChunk]:
        """
        [核心节点]：从本地加载企业级知识切片库
        
        输入：无
        输出：KnowledgeChunk 对象列表
        副作用：无
        
        原理：读取 data/enterprise_knowledge_base.json 并反序列化为企业知识切片
        """
        kb_path = Path("data/enterprise_knowledge_base.json")
        if not kb_path.exists():
            print("[!] 警告: 未找到企业知识库文件，返回空列表")
            return []
        
        with open(kb_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [KnowledgeChunk(**item) for item in data]
    
    def generate_reply(self, user_input: str, session_history: List[dict] = None, temperature: float = 0.7, frequency_penalty: float = 0.2, presence_penalty: float = 0.2, max_tokens: int = 500, stop_sequences: List[str] = None) -> Dict[str, any]:
        """
        [核心节点]：企业级专家回复生成链路
        
        输入：用户输入文本、短期会话历史、温度参数、频率惩罚、存在惩罚、最大Token数、停止序列
        输出：包含回复、业务意图、紧急程度、中间态数据的字典
        副作用：调用向量数据库和大模型 API
        
        原理：意图分诊 -> 知识召回 -> 企业级 Prompt 组装 -> 大模型生成
        """
        if stop_sequences is None:
            stop_sequences = ["\nCustomer:", "\nExpert:"]  # [核心节点]：B 端专业称谓
        print(f"\n{'='*80}")
        print("开始生成回复链路")
        print(f"{'='*80}")
        
        # 初始化 session_history
        if session_history is None:
            session_history = []
        
        # [核心节点]：第一步：业务意图分诊（动态意图探针，传入专家画像）
        print(f"\n[步骤 1] 业务意图分诊 - 动态意图探针检测")
        print(f"  用户输入: \"{user_input}\"")
        print(f"  短期记忆条数: {len(session_history)}")
        print(f"  当前专家: {self.expert_profile.expert_name}")
        print(f"  专属意图列表: {self.expert_profile.supported_intents}")
        # [核心节点]：传入专家画像，实现租户专属意图识别
        probe_state = self.intent_probe.classify(user_input, self.expert_profile)
        business_intent = probe_state.business_intent
        urgency_level = probe_state.urgency_level
        print(f"[动态探针] 识别业务意图：{business_intent}")
        print(f"[动态探针] 判定紧急程度：{urgency_level}")
        print(f"  ✓ 使用传入温度参数: {temperature}（B 端场景禁止自动调节）")
        
        # [核心节点]：第二步：记忆召回（RAG），算力风控检查
        print(f"\n[步骤 2] 记忆召回 - 向量数据库检索")
        rag_memories = []
        rag_metadata = []
        
        # [核心节点：算力风控机制]：判断是否为兜底意图，物理阻断向量检索
        fallback_intent = self.expert_profile.supported_intents[-1] if self.expert_profile.supported_intents else "闲聊兜底"
        is_fallback = (business_intent == fallback_intent)
        
        if is_fallback:
            print(f"[算力风控] 识别为兜底意图 '{business_intent}'，已物理阻断向量检索")
            print(f"[算力风控] 跳过向量数据库查询，节省算力消耗")
            rag_memories = []
        elif self.vector_db:
            try:
                # [核心节点]：多租户隔离 - 传入 expert_id 进行过滤
                # [核心节点]：使用混合检索引擎 (Dense + Sparse + Reranking)
                rag_results = self.vector_db.hybrid_search(
                    query=user_input, 
                    expert_id=self.expert_id,  # [核心节点]：租户隔离键
                    top_k=3
                )
                rag_memories = [result['text'] for result in rag_results]
                rag_metadata = [result['metadata'] for result in rag_results]
                print(f"[+] RAG 召回记忆条数：{len(rag_memories)}")
                for i, (memory, meta) in enumerate(zip(rag_memories, rag_metadata), 1):
                    timestamp = meta.get('start_timestamp', '未知时间')
                    print(f"    [{i}] 时间戳: {timestamp}")
                    print(f"        内容节选: {memory[:50]}...")
            except Exception as e:
                print(f"❌ [RAG 异常] {e}")
                print(f"[!] 降级使用传统检索器")
                rag_memories = []
        else:
            print(f"[!] 向量数据库未初始化，使用传统检索器")
            # [核心节点]：降级使用企业知识切片
            few_shots = self.retriever.get_contextual_knowledge(probe_state, self.knowledge_base, top_k=3)
            rag_memories = [f"知识切片: {chunk.content}\n类型: {chunk.chunk_type}\n来源: {chunk.citation_source}" for chunk in few_shots]
            print(f"[+] 传统检索召回知识切片数：{len(rag_memories)}")
        
        # [核心节点]：第三步：企业级 Prompt 组装
        print(f"\n[步骤 3] 企业级 Prompt 组装")
        system_prompt = self._build_rag_system_prompt(probe_state, rag_memories)
        # [物理切除]：表情包参数已物理删除，B 端系统不需要表情功能
        
        # 拼接顺序：System Prompt + session_history (短期记忆) + 当前 user_query
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加短期记忆（最近 5 轮）
        recent_history = session_history[-10:] if len(session_history) > 10 else session_history
        for msg in recent_history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        # 添加当前用户输入
        messages.append({"role": "user", "content": user_input})
        
        # [核心节点]：白盒化日志：打印各模块 Token 数
        print(f"  ✓ 系统提示词长度: {len(system_prompt)} 字符")
        print(f"  ✓ 消息历史数量: {len(messages)} 条")
        print(f"  ✓ 短期记忆条数: {len(recent_history)}")
        print(f"  ✓ Prompt 模块 Token 分布:")
        print(f"    - 专家人设: {len(self.expert_profile.expert_name)} 字符")
        print(f"    - 专业领域: {len(self.expert_profile.domain_expertise)} 字符")
        print(f"    - 业务意图: {len(business_intent)} 字符")
        print(f"    - 企业知识: {sum(len(m) for m in rag_memories)} 字符")
        print(f"    - 短期记忆: {sum(len(m.get('content', '')) for m in recent_history)} 字符")
        
        # [物理切除]：高光记忆触发机制已物理删除 - B 端企业系统不需要情感记忆锚点
        
        # [核心节点]：第四步：大模型生成
        print(f"\n[步骤 4] 大模型生成 - 调用 API")
        generation_start = time.time()
        try:
            response = self.client.chat.completions.create(
                model="deepseek-ai/DeepSeek-V3",
                messages=messages,
                temperature=temperature,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                max_tokens=max_tokens,
                stop=stop_sequences
            )
            reply = response.choices[0].message.content
            generation_time = time.time() - generation_start
            print(f"  ✓ 生成回复成功: {len(reply)} 字符")
            print(f"  ✓ 回复内容: {reply}")
            print(f"  ✓ 推理耗时: {generation_time:.2f} 秒")
            
        except Exception as e:
            # Fail Fast: 直接抛出原始错误，不使用降级方案
            raise RuntimeError(f"大模型 API 调用失败: {str(e)}")
        
        print(f"\n{'='*80}")
        print("生成回复链路完成")
        print(f"{'='*80}\n")
        
        # [核心节点]：返回包含企业级中间态数据的字典
        return {
            "reply": reply,
            "business_intent": business_intent,
            "urgency_level": urgency_level,
            "retrieved_memories": rag_memories,
            "prompt_length": len(system_prompt),
            "generation_time": generation_time
        }
    
    def _build_rag_system_prompt(self, probe_state: ProbeState, rag_memories: List[str]) -> str:
        """
        [核心节点]：构建企业级专家数字孪生系统提示词（含神经缝合与反机器味封印）
        
        输入：探针状态、召回的企业知识切片
        输出：完整的企业级系统提示词
        副作用：无
        
        原理：将专家画像、业务意图、企业知识、金牌示例、业务红线组装成结构化 Prompt
              并在结尾强制注入反机器味红线，确保回复像真人一样自然
        """
        try:
            print("[神经缝合] 开始组装企业级系统提示词...")
            profile = self.expert_profile
            prompt_parts = []
            
            # [核心节点]：专家身份与专业领域
            prompt_parts.append(f"专家角色: {profile.expert_name}")
            prompt_parts.append(f"专业领域: {profile.domain_expertise}")
            
            # [核心节点]：沟通风格（从 language_features 演变为专业沟通规范）
            if profile.communication_style:
                prompt_parts.append("\n沟通风格:")
                style = profile.communication_style
                if style.get('tone'):
                    prompt_parts.append(f"- 语气基调: {style['tone']}")
                if style.get('avg_response_length'):
                    prompt_parts.append(f"- 平均回复长度: {style['avg_response_length']} 字")
                if style.get('preferred_greeting'):
                    prompt_parts.append(f"- 标准问候语: {style['preferred_greeting']}")
            
            # [核心节点]：业务红线（绝不可违反）
            if profile.business_redlines:
                prompt_parts.append("\n业务红线 (绝不可违反):")
                for redline in profile.business_redlines:
                    prompt_parts.append(f"- {redline}")
            
            # [核心节点]：路由意图与紧急程度（替代情绪探针）
            prompt_parts.append(f"\n路由意图: {probe_state.business_intent}")
            prompt_parts.append(f"紧急程度: {probe_state.urgency_level}")
            
            # [核心节点]：企业知识切片参考
            if rag_memories:
                prompt_parts.append("\n企业知识切片参考（来自混合检索召回）:")
                for i, memory in enumerate(rag_memories, 1):
                    prompt_parts.append(f"\n知识切片 {i}:")
                    prompt_parts.append(memory)
            
            # [核心节点]：强化 RAG 降噪护栏
            prompt_parts.append("\n[RAG 降噪护栏]：")
            prompt_parts.append("如果你认为上述检索到的知识切片与用户的业务查询毫无逻辑关联，请【绝对无视】它们")
            prompt_parts.append("基于你的专业领域常识回答，或明确告知用户无法回答该问题")
            prompt_parts.append("严禁强行缝合不相关的知识切片到回复中")
            prompt_parts.append("B 端企业场景要求准确性优先，宁可承认不知道也不要编造")
            
            # [核心节点]：企业级任务指令
            prompt_parts.append("\n任务:")
            prompt_parts.append("你是一位专业的企业级数字孪生专家。基于以上专业画像、业务意图和企业知识，")
            prompt_parts.append("以专业、准确、简洁的方式回应用户的业务咨询或技术报障。")
            prompt_parts.append("回复必须符合业务红线、基于可靠知识、保持专业语气")
            
            # [神经缝合]：在 Prompt 结尾强制注入金牌示例（Golden Few-Shots）
            print("[神经缝合] 正在注入 Golden Few-Shots 进行语气校准...")
            if profile.golden_few_shots and len(profile.golden_few_shots) > 0:
                prompt_parts.append("\n金牌示例对话（必须完全模仿以下示例的语气、句式长短和标点习惯）:")
                for i, shot in enumerate(profile.golden_few_shots[:3], 1):  # 最多取3个示例
                    try:
                        user_input = shot.get('user_input', '')
                        expert_reply = shot.get('expert_reply', '')
                        if user_input and expert_reply:
                            prompt_parts.append(f"\n--- 示例 {i} ---")
                            prompt_parts.append(f"[示例 Q]: {user_input}")
                            prompt_parts.append(f"[示例 A]: {expert_reply}")
                    except Exception as e:
                        print(f"[神经缝合] 警告：组装第 {i} 个 few-shot 示例时出错: {e}")
                        continue
                print(f"[神经缝合] 成功注入 {min(len(profile.golden_few_shots), 3)} 个金牌示例")
            else:
                print("[神经缝合] 警告：专家画像中未找到 golden_few_shots，语气校准可能受限")
            
            # [终极反机器味红线]：在 Prompt 最后增加不可逾越的规则
            print("[神经缝合] 正在封印反机器味红线...")
            prompt_parts.append("\n" + "="*60)
            prompt_parts.append("【格式与语气绝对红线 - 不可逾越】")
            prompt_parts.append("="*60)
            prompt_parts.append("1. 绝对禁止使用 Markdown 语法（严禁出现 **加粗** 和 1. 2. 3. 列表）！")
            prompt_parts.append("""2. 绝对禁止使用"作为一名xxx专家"、"我建议"、"根据我的分析"等官腔废话！""")
            prompt_parts.append("3. 必须完全吸收并模仿上方【示例 A】中的口语化语气、句式长短和标点习惯！")
            prompt_parts.append("4. 用连续的自然段落回复，像真人一样对话，不要分段罗列！")
            prompt_parts.append("""5. 严禁输出"总结："、"综上所述"、"希望以上信息对您有帮助"、"如果您还有其他问题"等AI味收尾！""")
            prompt_parts.append("6. 直接回答问题，不要解释你的思考过程！")
            prompt_parts.append("="*60)
            
            final_prompt = "\n".join(prompt_parts)
            print(f"[神经缝合] 系统提示词组装完成，总长度: {len(final_prompt)} 字符")
            return final_prompt
            
        except Exception as e:
            print(f"[神经缝合] 致命错误：组装系统提示词时发生异常: {e}")
            print(f"[神经缝合] 异常类型: {type(e).__name__}")
            # 异常穿透：向上抛出，让上层处理
            raise

```

### 📄 services/state_tracker.py
```python
"""
业务意图探针 - Business Intent Probe
企业级语义分类引擎 (Semantic Routing Engine)，基于 LLM 进行业务意图识别和紧急程度判断
"""

import json
import traceback
from typing import Optional
from domain.models import ProbeState, DigitalTwinProfile
import openai
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()


class BusinessIntentProbe:
    """
    业务意图探针
    使用轻量级 LLM 对用户输入进行业务意图分诊和紧急程度判断
    扮演高精度语义分类引擎，精准识别用户需求
    """
    
    def __init__(self):
        """初始化业务意图探针"""
        self.client = openai.OpenAI(
            api_key=os.getenv("SILICONFLOW_API_KEY"),
            base_url=os.getenv("BASE_URL")
        )
        self.model = "Qwen/Qwen2.5-7B-Instruct"
    
    def classify(self, user_input: str, expert_profile: DigitalTwinProfile) -> ProbeState:
        """
        [核心节点：动态意图探针] 使用 LLM 对用户输入进行租户专属业务意图分类
        
        输入：
            - user_input: 用户输入文本
            - expert_profile: 专家画像（包含 supported_intents 租户专属意图列表）
        输出：经过 Pydantic 强校验的探针状态对象
        副作用：如果分类失败或意图不在支持列表中，降级为兜底意图
        
        用途：基于专家画像的动态意图列表，精准识别用户业务意图和紧急程度
        """
        # [核心节点]：提取租户专属意图列表
        intents = expert_profile.supported_intents
        fallback_intent = intents[-1] if intents else "闲聊兜底"
        
        # [核心节点]：动态组装 System Prompt，将硬编码意图替换为专家专属意图
        intents_list_str = "\n".join([f"- {intent}" for intent in intents])
        
        # [核心节点]：去人格化 Prompt，抽象紧急程度描述，解决领域偏见问题
        system_prompt = f"""你是一个高精度的企业级语义分类引擎 (Semantic Routing Engine)。请根据用户的话语，精准识别其业务意图和紧急程度，以便将其路由到对应的专家。

【专家专属意图分类】（必须选择其一）：
{intents_list_str}

紧急程度分类（必须选择其一）：
- 高: 严重阻断核心业务，或造成重大实际损失/生命财产威胁
- 中: 业务部分受损，体验下降，但存在临时替代方案
- 低: 常规信息咨询，无实质性损失

请严格以纯 JSON 格式输出，不要包含任何其他文字说明，格式如下：
{{
    "business_intent": "业务意图",
    "urgency_level": "紧急程度"
}}"""
        
        try:
            # [核心节点]：此处调用轻量级 LLM 对用户 query 进行分诊路由
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=0.1,
                max_tokens=100,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            result_dict = json.loads(result_text)
            
            # [核心节点]：Pydantic 降级防线 - 校验大模型输出的意图是否在支持列表中
            detected_intent = result_dict.get("business_intent", fallback_intent)
            urgency_level = result_dict.get("urgency_level", "低")
            
            # [核心节点]：意图合法性校验，防止大模型幻觉输出不存在的意图
            if detected_intent not in intents:
                print(f"[动态探针] 检测到非法意图 '{detected_intent}'，强制降级为兜底意图 '{fallback_intent}'")
                detected_intent = fallback_intent
            else:
                print(f"[动态探针] 意图识别成功: {detected_intent}")
            
            probe_state = ProbeState(
                business_intent=detected_intent,
                urgency_level=urgency_level,
                confidence=1.0
            )
            
            return probe_state
            
        except Exception as e:
            # [核心节点]：此处实现保底机制，降级为兜底意图
            print(f"[!] 业务意图探针分类失败: {e}")
            print(f"[!] 错误堆栈: {traceback.format_exc()}")
            
            # [核心节点]：降级到兜底意图（最后一个意图）
            print(f"[动态探针] 异常降级，使用兜底意图: {fallback_intent}")
            return ProbeState(
                business_intent=fallback_intent,
                urgency_level="低",
                confidence=0.0
            )

```

### 📄 web_ui.py
```python
"""
企业级专家数字孪生系统 - B 端业务沙盘前端
纯粹的呈现层，通过 HTTP 调用后端 FastAPI 网关
遵循企业级工程宪法的端云解耦原则

[核心节点]：多租户专家池架构 - 支持动态切换不同专家

【启动命令】（重要！避开 8501 端口冲突）
    streamlit run web_ui.py --server.port 8502

【如遇 8501 端口被占用】
    1. 查找占用进程: netstat -ano | findstr :8501
    2. 结束占用进程: taskkill /F /PID <PID>
    3. 或直接换用 8502 端口启动
"""

# [核心节点]：Streamlit 端口配置（避开 8501 冲突）
# 建议启动命令: streamlit run web_ui.py --server.port 8502

import streamlit as st
import requests
import os
import sys
import json
from typing import List, Dict
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# [核心节点]：导入专家管理器
from services.expert_manager import get_expert_manager

# [核心节点]：配置页面 - 宽屏布局
st.set_page_config(
    page_title="专家数字孪生系统 V1.0",
    page_icon="🤖",
    layout="wide"
)

# API 端点配置
API_URL = "http://localhost:8088/api/v1/chat"
LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "system_trace.log")

# 初始化会话状态
if "messages" not in st.session_state:
    st.session_state.messages = []
if "latest_trace" not in st.session_state:
    st.session_state.latest_trace = {}
if "temperature" not in st.session_state:
    st.session_state.temperature = 0.3  # [核心节点]：企业级场景要求确定性，低温设置
if "frequency_penalty" not in st.session_state:
    st.session_state.frequency_penalty = 0.2
if "presence_penalty" not in st.session_state:
    st.session_state.presence_penalty = 0.2
if "max_tokens" not in st.session_state:
    st.session_state.max_tokens = 500  # [核心节点]：企业级回复需要更详细解释
if "stop_sequences" not in st.session_state:
    st.session_state.stop_sequences = ["\nCustomer:", "\nExpert:"]  # [核心节点]：B 端专业称谓

# [核心节点]：多租户专家池 - 初始化专家选择状态
if "current_expert_id" not in st.session_state:
    st.session_state.current_expert_id = None
if "expert_list" not in st.session_state:
    st.session_state.expert_list = []

# [核心节点]：初始化专家管理器并加载专家列表
def load_expert_list():
    """加载可用专家列表"""
    try:
        expert_manager = get_expert_manager()
        experts = expert_manager.list_experts()
        return experts
    except Exception as e:
        st.error(f"加载专家列表失败: {e}")
        return []

# 初始加载专家列表
if not st.session_state.expert_list:
    st.session_state.expert_list = load_expert_list()

def clear_chat_history():
    """清除聊天历史"""
    st.session_state.messages = []
    st.session_state.latest_trace = {}
    st.rerun()

def send_message(user_input: str, session_history: List[dict], params: Dict) -> Dict:
    """
    发送消息到后端 API
    
    输入：用户输入文本、短期会话历史、参数字典
    输出：API 响应字典
    副作用：无
    
    原理：通过 HTTP POST 请求调用 FastAPI 网关
    """
    try:
        payload = {
            "user_query": user_input,
            "session_history": session_history,
            **params
        }
        response = requests.post(API_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"error": "网络断开"}
    except requests.exceptions.Timeout:
        return {"error": "请求超时"}
    except Exception as e:
        return {"error": f"未知错误: {str(e)}"}

def load_system_trace():
    """
    加载系统追踪日志
    
    输入：无
    输出：日志列表
    副作用：无
    
    原理：读取 logs/system_trace.log 文件并解析 JSONL
    """
    if not os.path.exists(LOG_FILE):
        return []
    
    logs = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return logs

def clear_system_trace():
    """
    清空系统追踪日志
    
    输入：无
    输出：无
    副作用：删除日志文件
    
    原理：删除 logs/system_trace.log 文件
    """
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
        st.success("系统日志已清空")
        st.rerun()

# ========== 界面布局 ==========

# [核心节点]：左侧边栏 - 页面路由与专家档案室
with st.sidebar:
    st.title("专家数字孪生系统 V1.0")
    st.markdown("---")
    
    # [核心节点]：端口配置提示（解决 8501 冲突问题）
    with st.expander("⚙️ 端口配置", expanded=False):
        st.info("""
        **默认端口 8501 被占用？**
        
        使用以下命令启动：
        ```bash
        streamlit run web_ui.py --server.port 8502
        ```
        
        或结束占用进程：
        ```bash
        netstat -ano | findstr :8501
        taskkill /F /PID <PID>
        ```
        """)
    
    # [核心节点]：多租户专家档案室 - 动态专家选择
    st.markdown("### 🏢 专家档案室")
    st.caption("选择数字孪生专家进行对话")
    
    # 刷新专家列表按钮
    col_refresh, col_dummy = st.columns([1, 2])
    with col_refresh:
        if st.button("🔄 刷新", key="refresh_experts"):
            st.session_state.expert_list = load_expert_list()
            st.rerun()
    
    # 专家下拉选择框
    if st.session_state.expert_list:
        expert_options = {f"{e['expert_name']} ({e['expert_id']})": e['expert_id'] 
                         for e in st.session_state.expert_list}
        
        # 如果没有选择专家，默认选择第一个
        if st.session_state.current_expert_id is None:
            st.session_state.current_expert_id = st.session_state.expert_list[0]['expert_id']
        
        # 找到当前显示名称
        current_display = None
        for display, exp_id in expert_options.items():
            if exp_id == st.session_state.current_expert_id:
                current_display = display
                break
        
        selected_expert = st.selectbox(
            "选择专家",
            options=list(expert_options.keys()),
            index=list(expert_options.values()).index(st.session_state.current_expert_id) if current_display else 0,
            label_visibility="collapsed"
        )
        
        # 检测专家切换
        new_expert_id = expert_options[selected_expert]
        if new_expert_id != st.session_state.current_expert_id:
            # [核心节点]：切换专家时清空对话历史
            st.session_state.current_expert_id = new_expert_id
            st.session_state.messages = []
            st.session_state.latest_trace = {}
            st.success(f"已切换至专家: {selected_expert}")
            st.rerun()
        
        # 显示当前专家信息
        current_expert = next(
            (e for e in st.session_state.expert_list if e['expert_id'] == st.session_state.current_expert_id),
            None
        )
        if current_expert:
            st.info(f"**当前专家**: {current_expert['expert_name']}")
            st.caption(f"领域: {current_expert['domain_expertise']}")
    else:
        st.warning("⚠️ 暂无可用专家")
        st.info("请先运行 ETL 流程创建专家")
        # 创建占位符 expert_id 避免错误
        st.session_state.current_expert_id = "default_expert"
    
    st.markdown("---")
    
    # [核心节点]：多页面路由 - B 端业务沙盘与 CTO 观测站
    page = st.radio(
        "选择视图",
        ["🏢 B端业务沙盘", "📡 CTO全息观测站"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    st.markdown("### 系统状态")
    st.info(f"后端地址: {API_URL}")
    st.caption("端云解耦架构 | 多租户专家池 | 全息监控")

# [核心节点]：视图 A - B 端业务沙盘
if page == "🏢 B端业务沙盘":
    st.title("对话界面")
    
    # 渲染历史消息
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # 底部输入框
    if user_input := st.chat_input("输入消息..."):
        # 添加用户消息到历史
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        # 渲染用户消息
        with st.chat_message("user"):
            st.markdown(user_input)
        
        # 准备短期记忆（最近 10 条）
        session_history = st.session_state.messages[-10:] if len(st.session_state.messages) > 10 else st.session_state.messages
        
        # [核心节点]：构造请求参数 - 包含专家 ID 用于多租户路由
        params = {
            "expert_id": st.session_state.current_expert_id,  # [核心节点]：多租户专家池路由键
            "temperature": st.session_state.temperature,
            "frequency_penalty": st.session_state.frequency_penalty,
            "presence_penalty": st.session_state.presence_penalty,
            "max_tokens": st.session_state.max_tokens,
            "stop_sequences": st.session_state.stop_sequences
        }
        
        # 调用后端 API
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                response = send_message(user_input, session_history, params)
                
                if "error" in response:
                    st.error(f"[网络断开] 无法连接到神经中枢，请检查后端网关是否启动。")
                    st.caption(f"错误详情: {response['error']}")
                else:
                    reply = response.get("reply", "")
                    st.markdown(reply)
                    
                    # [核心节点]：保存追踪数据 - 企业级字段：业务意图 + 紧急程度
                    st.session_state.latest_trace = {
                        "user_input": user_input,
                        "business_intent": response.get("business_intent", "CHIT_CHAT"),
                        "urgency_level": response.get("urgency_level", "低"),
                        "retrieved_memories": response.get("retrieved_memories", []),
                        "reply": reply,
                        "prompt_length": response.get("prompt_length", 0),
                        "generation_time": response.get("generation_time", 0.0),
                        "temperature": params["temperature"]
                    }
                    
                    # 添加 AI 回复到历史
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": reply
                    })
                    
                    # 强制刷新
                    st.rerun()

# ========== 视图 B: CTO全息观测站 ==========
elif page == "📡 CTO全息观测站":
    st.title("📡 CTO 全息观测站")
    st.markdown("---")
    
    # 左右分列布局
    left_col, right_col = st.columns([1, 2])
    
    # 左列：上帝调参台
    with left_col:
        st.markdown("### 🎛️ 上帝调参台")
        st.markdown("---")
        
        # [核心节点]：温度范围调整为 0.1-1.0，企业级场景要求确定性
        st.session_state.temperature = st.slider(
            "🌡️ 温度 (Temperature)",
            min_value=0.1,
            max_value=1.0,
            value=st.session_state.temperature,
            step=0.1,
            help="B 端企业场景建议低温设置以确保专业准确性"
        )
        
        st.session_state.frequency_penalty = st.slider(
            "🔁 频率惩罚 (Frequency Penalty)",
            min_value=0.0,
            max_value=2.0,
            value=st.session_state.frequency_penalty,
            step=0.1,
            help="防复读惩罚，降低重复内容的概率"
        )
        
        st.session_state.presence_penalty = st.slider(
            "🆕 存在惩罚 (Presence Penalty)",
            min_value=0.0,
            max_value=2.0,
            value=st.session_state.presence_penalty,
            step=0.1,
            help="新话题激励，鼓励模型讨论新话题"
        )
        
        st.session_state.max_tokens = st.slider(
            "📏 最大 Token 数 (Max Tokens)",
            min_value=50,
            max_value=1000,
            value=st.session_state.max_tokens,
            step=50,
            help="最大生成 Token 数，防小作文"
        )
        
        # [物理切除]：表情包参数已物理删除 - B 端企业系统不需要表情功能
        
        st.markdown("---")
        
        if st.button("🔄 新建对话", use_container_width=True):
            clear_chat_history()
    
    # 右列：全生命周期 X光透视
    with right_col:
        st.markdown("### 🔬 全生命周期 X光透视 (Trace)")
        st.markdown("---")
        
        if st.session_state.latest_trace:
            trace = st.session_state.latest_trace
            
            # [核心节点]：数据流向图 - 企业级业务意图路由可视化
            st.markdown("#### 🔄 数据流向图")
            st.code(f"""
User Input: "{trace['user_input'][:50]}..."
    ↓
[节点 1: 意图分诊] → Intent: {trace['business_intent']} | Urgency: {trace['urgency_level']}
    ↓
[节点 2: RAG 召回] → {len(trace['retrieved_memories'])} 条企业知识切片
    ↓
[节点 3: 最终 Prompt] → {trace['prompt_length']} 字符
    ↓
[节点 4: 算力结算] → {trace['generation_time']:.2f} 秒
    ↓
Reply → {len(trace['reply'])} 字符
            """, language="text")
            
            st.markdown("---")
            
            # [核心节点]：意图分诊 - 显示业务意图和紧急程度
            st.markdown("#### [节点 1: 意图分诊]")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("业务意图", trace['business_intent'])
            with col2:
                st.metric("紧急程度", trace['urgency_level'])
            with col3:
                st.metric("温度参数", f"{trace['temperature']:.1f}")
            
            st.markdown("---")
            
            # 节点 2: RAG 召回
            st.markdown("#### [节点 2: RAG 召回]")
            if trace['retrieved_memories']:
                for i, memory in enumerate(trace['retrieved_memories'], 1):
                    st.markdown(f"**记忆切片 {i}**:")
                    st.code(memory, language="text")
            else:
                st.warning("未触发历史记忆")
            
            st.markdown("---")
            
            # 节点 3: 最终 Prompt
            st.markdown("#### [节点 3: 最终 Prompt]")
            with st.expander("查看完整 System Prompt"):
                st.code(f"System Prompt 长度: {trace['prompt_length']} 字符\n\n(完整 Prompt 内容仅在 CTO 控制台可见)", language="text")
            
            st.markdown("---")
            
            # 节点 4: 算力结算
            st.markdown("#### [节点 4: 算力结算]")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Prompt 长度", f"{trace['prompt_length']} 字符")
            with col2:
                st.metric("推理耗时", f"{trace['generation_time']:.2f} 秒")
        else:
            st.info("暂无追踪数据，请先在 B端业务沙盘进行对话")
    
    st.markdown("---")
    
    # 系统日志监控
    st.markdown("### 📋 系统日志监控")
    logs = load_system_trace()
    
    if not logs:
        st.info("暂无系统日志数据")
    else:
        # [核心节点]：系统日志监控 - 展示业务意图和紧急程度而非情绪
        st.dataframe(
            logs,
            column_config={
                "timestamp": st.column_config.DatetimeColumn("时间戳", format="YYYY-MM-DD HH:mm:ss"),
                "user_input": "用户输入",
                "business_intent": "业务意图",
                "urgency_level": "紧急程度",
                "generation_time": st.column_config.NumberColumn("推理耗时(秒)", format="%.2f"),
                "prompt_length": "Prompt长度",
                "temperature": "温度"
            },
            use_container_width=True
        )
        
        st.markdown("---")
        
        # 推理耗时监控图
        st.markdown("### 📈 推理耗时监控")
        if len(logs) > 1:
            chart_data = {
                "时间": [log["timestamp"] for log in logs],
                "推理耗时(秒)": [log["generation_time"] for log in logs]
            }
            st.line_chart(chart_data, x="时间", y="推理耗时(秒)")
        else:
            st.caption("数据不足，无法绘制图表")
        
        st.markdown("---")
        
        # 清空日志按钮
        if st.button("🗑️ 清空系统日志", use_container_width=True):
            clear_system_trace()

```

### 📄 engineering_norms.md
```markdown
# 《AI 架构工程宪法 V2.0》

## 1. 零回归与防腐层原则 (Zero-Regression & ACL)
- 修复 Bug 或新增特性时，必须进行最小化修改，严禁重写稳定逻辑。
- 外部开源工具（如 SillyTavern）仅视为下游消费者。系统内部必须建立 `UnifiedAdapter`（统一适配器）作为防腐层，隔离外部格式变化对内部数据契约的污染。

## 2. 数据契约与 Pydantic 护城河
- 模块间传递必须使用 `domain/models.py` 中定义的类。
- **反 LLM 谄媚机制 (Anti-Sycophancy)：** 所有接收大模型输出的文本字段，必须使用 Pydantic 的 `@field_validator` 进行正则清洗，物理斩断"从对话中可以看出"、"作为一个AI"等废话前缀。

## 3. 数学+AI 双重过滤原则 (Math-LLM Hybrid Pipeline)
- 严禁让大模型"一口吞下"海量数据进行盲目统计。
- 提取【行业黑话/专业术语/SOP 流程节点】等客观特征时，必须先用 Python 原生库（如 `collections.Counter` / N-gram 分词）进行物理词频统计，然后将【Top N 真实高频专业词汇】送给大模型进行业务价值筛选。用统计学锁死大模型的业务幻觉。

## 4. 彻底的泛化解耦 (Generalization)
- 业务代码中（如 `state_tracker.py`）绝对禁止出现特定企业名称或特定客户名的硬编码。
- 必须构建 Zero-Shot 动态分类器，基于配置驱动，而非代码驱动。
- **业务意图路由 (Intent Router)**：判断请求是技术支持、商务报价、还是客情闲聊。

## 5. 面向 AI 与架构师的极致注释协议 (AI-Oriented Commenting)

### 铁律 1：业务界碑
- 所有 `class` 和 `def` 必须配有大白话的中文 Docstring
- Docstring 必须明确说明：输入什么、输出什么、副作用是什么
- 示例格式：
  ```python
  def process_data(raw_input: str) -> dict:
      """
      处理原始数据，提取关键信息
      
      Args:
          raw_input: 原始文本输入
          
      Returns:
          包含提取信息的字典
          
      Side Effects:
          会打印处理进度日志
      """
  ```

### 铁律 2：逻辑节点透视
- 在代码的每一个关键核心流转处，必须上方空一行，写入双斜杠中文注释
- 注释格式：`# [核心节点]：此处利用 Pydantic 过滤掉大模型生成的废话前缀`
- 核心流转包括：开始调用大模型、开始清洗数据、正则拦截处、数据转换处

### 铁律 3：零术语壁垒
- 注释必须做到让只懂基础语法的架构师能够完全看懂业务走向
- 禁止使用晦涩的技术术语，必须用大白话解释业务逻辑
- 这是未来所有代码生成的强制标准

## 数据契约 (Data Contract)

### 身份映射
- **Client (客户)**: 从 `.env` 或接口动态读取
- **Expert (专家)**: {{EXPERT_ROLE}}（如：金牌架构师、资深法务，从 `.env` 读取）

### 核心数据文件（全新定义）
- `data/expert_profile.json`: 专家知识基座（SOP 规范、专业术语边界、合规红线）
- `data/enterprise_knowledge_base.json`: 结构化企业语料库（如 QA 对、历史工单、产品白皮书切片）
- `raw_enterprise_corpus.txt/csv`: 原始企业脏数据源

## 接口说明

### 企业级 API 网关契约 (api_gateway.py)

#### 核心接口
- **唯一对外暴露接口**: `POST /api/v1/expert/chat`
- **并发支持**: 必须支持并发处理，严禁在全局变量中存储单一用户状态
- **请求格式**: JSON 格式，包含 client_id、expert_role、query 等字段
- **响应格式**: JSON 格式，包含 reply、intent_routed、generation_time 等字段

#### 业务意图路由
- 自动识别请求类型：技术支持、商务报价、客情闲聊
- 根据意图路由到不同的专家模型或处理逻辑
- 支持动态专家角色切换

## 部署禁令

### 严禁操作
- **严禁重写**: 所有文件操作仅允许修改，禁止完全重写文件
- **严禁硬编码路径**: 必须使用 `os.path.abspath(os.path.dirname(__file__))` 动态获取路径
- **严禁零散脚本**: 禁止创建孤立的一次性转换脚本

### 强制规范
- 所有文件读写必须使用动态路径
- 每个方法必须包裹在 `try-except` 中
- 异常日志格式: `❌ [适配器异常] {e}`
- 成功日志格式: `[+] 成功清除语料库中 {n} 条重复项`、`[+] 酒馆全套数据包 (Card/Book/RAG) 已全自动产出至 data/ 目录`

## 流水线集成

### 自动触发机制
- 在 `api_gateway.py` 或 `main.py` 的初始化阶段自动触发适配器运行
- 确保 SillyTavern 拿到的永远是最新且清洗过的干净数据
- 单一事实来源 (Single Source of Truth): 所有导出基于核心 JSON 文件

## 6. LLMOps 可观测性铁律 (Observability)

### 核心要求
- 所有微服务项目必须具备独立的 LLMOps 监控面板。
- 记录规范：每一次大模型调用的 Request、Response、耗时、Tokens、RAG 命中切片，必须以 JSONL 格式异步写入 `logs/system_trace.log`，以便监控大盘读取分析。

### 日志格式规范
每行日志必须包含以下字段：
```json
{
  "timestamp": "ISO8601格式时间戳",
  "user_input": "用户输入文本",
  "detected_intent": "检测到的业务意图",
  "retrieved_memories": ["RAG召回的记忆切片"],
  "reply": "AI回复",
  "generation_time": "推理耗时(秒)",
  "prompt_length": "Prompt长度(字符)",
  "temperature": "企业级默认保持低温度 (0.1 - 0.3) 以保证确定性，仅在客情闲聊意图下动态调高"
}
```

### 监控大盘要求
- 必须提供实时数据表格展示
- 必须提供推理耗时监控图表
- 必须支持日志清空功能

## 7. 活文档与小白级说明书同步铁律 (Living Documentation)
- **唯一入口：** 项目根目录下的 `README.md` 是本系统唯一的"小白级操作指南"。
- **动态更新：** 任何涉及系统架构升级、端口变更、启动命令修改的操作，执行层 AI 必须**同步修改** `README.md`。
- **零门槛原则：** `README.md` 必须拒绝堆砌晦涩术语。必须包含"如何一键启动"、"去哪里看监控大屏"、"如何导入数据"的傻瓜式（Step-by-Step）操作步骤，确保不懂代码的业务人员能从零上手。

## 8. 面向指挥官的汉化交互原则 (Commander-Facing Localization)
- 所有终端打印的日志、系统的报错提示、Web UI 的展现文案，必须 100% 使用专业、易懂的中文大白话。
- 你在执行或者思考代码编写，架构升级过程中的流程语言也要使用中文确保指挥官读取。
- 严禁在终端抛出未经捕获包装的纯英文 traceback 吓唬指挥官。异常必须被 try-except 捕获，并转化为如"[致命拦截] JSON 解析失败，已触发大模型自纠错..."等中文提示。

## 版本历史
- v1.0 (2026-04-27): 初始版本，确立数据契约和工程规范
- v2.0 (2026-04-28): 工业级重构，颁布零回归、Pydantic 护城河、数学+AI 双重过滤、彻底泛化解耦四大原则
- v3.0 (2026-04-29): 新增 LLMOps 可观测性铁律，强制要求日志记录与监控大盘
- v4.0 (2026-05-05): 剥离 C 端情感模块，全面转型 B 端企业专家数字孪生系统，升级意图路由与专业术语过滤机制

```
