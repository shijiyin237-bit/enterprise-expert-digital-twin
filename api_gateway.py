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
