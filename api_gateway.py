"""
FastAPI 统一网关 - Project 6.0 Persona Engine
对外提供 RESTful API 接口，内部调用 PersonaAgent 生成回复
"""

import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import uvicorn
import os
import sys
import json
import traceback
from datetime import datetime
import openai

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

def write_system_trace(user_input: str, business_intent: str, urgency_level: str, retrieved_memories: List, reply: str, generation_time: float, prompt_length: int, temperature: float):
    """
    [强力防坍塌重构] 写入系统追踪日志
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
    try:
        # [核心节点]： Windows 平台下强力 I/O 护栏，防止并发冲突击穿网关
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[!] 警告：系统追踪日志写入失败（可能由于 Windows 并发文件锁冲突），已物理拦截异常，网关平稳运行。原因: {e}")



# Pydantic 契约定义
class ChatRequest(BaseModel):
    """企业级对话请求契约"""
    expert_id: Optional[str] = Field(
        default=None,
        description="目标专家的唯一标识符。若不传，系统会自动降级采用当前的默认专家，保障 100% 向下兼容",
        examples=["expert_20260509_170336"]
    )
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
    retrieved_memories: List = Field(
        default_factory=list,
        description="RAG 召回的企业级知识切片（富文本遥测数据），包含重排得分、知识溯源、切片类型等硬核指标，用于 CTO 全息监控",
        examples=[
            [{"text": "502 错误如何排查？", "score": 0.85, "citation_source": "运维手册", "chunk_type": "QA_PAIR"}],
            ["Q: 502 错误如何排查？A: 检查后端服务状态..."]  # 向后兼容
        ]
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
        description="切换后的专家名称",
        examples=["金牌架构师", "资深法务顾问"]
    )


class TitleRequest(BaseModel):
    """标题生成请求契约"""
    user_query: str = Field(
        ...,
        description="用户输入的查询内容，用于生成会话标题",
        examples=["服务器一直报 502 错误怎么排查？", "请问企业版 API 额度如何计费？"]
    )


class TitleResponse(BaseModel):
    """标题生成响应契约"""
    title: str = Field(
        ...,
        description="生成的会话标题，极简不超过6个字",
        examples=["服务器502报错", "API额度计费", "产品功能咨询"]
    )


class AsyncAgentPool:
    """
    企业级无状态异步 Agent 缓存池 (Thread-safe & Async non-blocking)
    以 expert_id 为 Key，缓存已初始化的 ExpertDigitalTwinAgent 实例。
    利用 asyncio.to_thread 将重度磁盘 I/O 剥离出主事件循环，实现真正的多租户高并发。
    """
    def __init__(self):
        self._pool: Dict[str, ExpertDigitalTwinAgent] = {}
        self._lock = asyncio.Lock()
        self.default_expert_id: Optional[str] = None
    
    async def get_agent(self, expert_id: str) -> ExpertDigitalTwinAgent:
        """线程安全、非阻塞的 Agent 获取与冷启动创建"""
        if expert_id not in self._pool:
            async with self._lock:
                # 双重检查锁，防并发冷启动穿透
                if expert_id not in self._pool:
                    print(f"[AgentPool] 正在异步冷启动加载专家实例: {expert_id}...")
                    # [核心节点]：使用 asyncio.to_thread 剥离同步重度 I/O，保障 Uvicorn 零阻塞
                    new_agent = await asyncio.to_thread(ExpertDigitalTwinAgent, expert_id=expert_id)
                    self._pool[expert_id] = new_agent
                    print(f"[AgentPool] 专家 [{new_agent.expert_profile.expert_name}] 加载完成，并入缓存池。")
        return self._pool[expert_id]
    
    async def reload_agent(self, expert_id: str) -> ExpertDigitalTwinAgent:
        """强制重载缓存池中的特定专家实例（热更新/重炼）"""
        async with self._lock:
            print(f"[AgentPool] 正在强制重载专家缓存: {expert_id}...")
            new_agent = await asyncio.to_thread(ExpertDigitalTwinAgent, expert_id=expert_id)
            self._pool[expert_id] = new_agent
            return new_agent


# [核心节点]：初始化 FastAPI 企业级网关
app = FastAPI(
    title="企业级专家数字孪生系统网关",
    description="B 端企业级专家数字孪生对话系统 - 基于业务意图探针与企业知识切片",
    version="1.0.0"
)

# [核心节点]：声明全局无状态 Agent 缓存池（替代旧的全局 agent 变量）
agent_pool = AsyncAgentPool()


# [核心节点]：系统异步点火与默认专家常驻内存预热
@app.on_event("startup")
async def startup_event():
    """系统异步点火与默认专家常驻内存预热"""
    print("[系统点火] 正在探测已炼丹的专家数据...")
    default_id = get_default_expert_id()
    if not default_id:
        print("[错误] 未找到任何已炼丹的专家数据，请先运行 etl_pipeline.py")
        sys.exit(1)
    
    agent_pool.default_expert_id = default_id
    print(f"[系统点火] 正在异步预载默认专家: {default_id} (Pre-warming)...")
    # 预热默认专家，确保首个请求 0ms 延迟
    await agent_pool.get_agent(default_id)
    print("[系统点火] 默认专家已载入内存，网关正式上线！\n")


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
    """健康检查接口 - 从 agent_pool 动态读取默认专家完成自检"""
    default_agent = await agent_pool.get_agent(agent_pool.default_expert_id)
    return {
        "status": "healthy",
        "expert_name": default_agent.expert_profile.expert_name,
        "knowledge_base_size": len(default_agent.knowledge_base)
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
    聊天接口 - 纯无状态多租户分流模式
    
    动态解析目标 expert_id，从 AsyncAgentPool 缓存池中异步获取 Agent 实例，
    将重度推理与重排 offload 到后台线程池，主事件循环高并发零假死。
    
    Args:
        request: 包含 user_query 和可选 expert_id 的请求体
        
    Returns:
        ChatResponse: 包含回复、业务意图和紧急程度的响应
    """
    try:
        print(f"\n[API] 收到聊天请求: \"{request.user_query}\"")
        
        # [核心节点]：动态解析目标 expert_id（多租户分流）
        target_expert_id = request.expert_id or agent_pool.default_expert_id
        print(f"    - 目标专家: {target_expert_id}")
        
        # [核心节点]：从 AsyncAgentPool 缓存池中异步获取 Agent 实例
        agent = await agent_pool.get_agent(target_expert_id)
        
        # [核心节点]：重度推理与重排 offload 到后台线程池，主事件循环高并发零假死
        result = await asyncio.to_thread(
            agent.generate_reply,
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
    description="动态切换当前激活的专家，无需重启服务。接收 expert_id 参数，通过 AsyncAgentPool 刷新缓存池。",
    tags=["多租户专家管理"]
)
async def switch_expert(request: SwitchExpertRequest):
    """
    切换专家接口 - 多租户架构核心功能
    
    允许指挥官在运行时切换不同专家（如从儿科切换到法律），无需重启服务。
    通过 agent_pool.reload_agent() 刷新缓存池，彻底去除危险的 global agent 全局变量修改。
    
    Args:
        request: 包含目标 expert_id 的请求体
        
    Returns:
        SwitchExpertResponse: 切换结果，包含成功状态和当前专家名称
    """
    try:
        print(f"\n[多租户切换] 收到专家切换请求: {request.expert_id}")
        
        # 验证专家是否存在
        experts_dir = os.path.join(os.path.dirname(__file__), "data", "experts")
        target_expert_path = os.path.join(experts_dir, request.expert_id)
        
        if not os.path.exists(target_expert_path) or not os.listdir(target_expert_path):
            print(f"[多租户切换] 专家不存在或目录为空: {request.expert_id}")
            # 从缓存池获取当前默认专家名称用于响应
            current_agent = await agent_pool.get_agent(agent_pool.default_expert_id)
            return SwitchExpertResponse(
                success=False,
                message=f"专家 '{request.expert_id}' 不存在或未完成炼丹，请检查 expert_id",
                expert_name=current_agent.expert_profile.expert_name
            )
        
        # [核心节点]：通过 agent_pool.reload_agent() 刷新缓存池，彻底去除危险的 global agent
        print(f"[多租户切换] 正在通过 AsyncAgentPool 重载专家: {request.expert_id}")
        new_agent = await agent_pool.reload_agent(request.expert_id)
        
        # [核心节点]：同步更新默认 expert_id，使后续无 expert_id 的请求自动路由到新专家
        agent_pool.default_expert_id = request.expert_id
        
        print(f"[多租户切换] 专家切换成功！当前专家: [{new_agent.expert_profile.expert_name}]")
        
        return SwitchExpertResponse(
            success=True,
            message=f"专家切换成功，当前以【{new_agent.expert_profile.expert_name}】身份应答",
            expert_name=new_agent.expert_profile.expert_name
        )
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"[多租户切换] 切换失败:")
        print(error_traceback)
        # 从缓存池获取当前默认专家名称用于响应
        current_agent = await agent_pool.get_agent(agent_pool.default_expert_id)
        return SwitchExpertResponse(
            success=False,
            message=f"专家切换失败: {str(e)}",
            expert_name=current_agent.expert_profile.expert_name
        )



@app.post("/api/v1/generate_title", response_model=TitleResponse)
async def generate_title(request: TitleRequest):
    """
    生成会话标题 API
    
    输入：用户查询内容
    输出：简洁的会话标题（不超过6个字）
    
    原理：调用大模型生成概括性标题，用于会话管理
    """
    try:
        # 初始化 OpenAI 客户端
        client = openai.OpenAI(
            api_key=os.getenv("SILICONFLOW_API_KEY"),
            base_url=os.getenv("BASE_URL")
        )
        
        # 构建标题生成 Prompt
        prompt = f"你是一个标题生成器。请根据用户的这句话，生成一个简洁的概括性标题（要求：极简，绝对不要超过 6 个字，不要标点符号）。用户原话：{request.user_query}"
        
        # 调用大模型生成标题
        response = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=20
        )
        
        # 提取生成的标题
        title = response.choices[0].message.content.strip()
        
        # 清理标题：移除多余空格和标点
        title = title.replace(" ", "").replace("。", "").replace("？", "").replace("！", "").replace("、", "")
        
        # 确保标题不超过6个字
        if len(title) > 6:
            title = title[:6]
        
        print(f"[标题生成] 用户原话: {request.user_query}")
        print(f"[标题生成] 生成标题: {title}")
        
        return TitleResponse(title=title)
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"[标题生成] 生成失败:")
        print(error_traceback)
        
        # 降级返回默认标题
        default_title = "新对话"
        return TitleResponse(title=default_title)


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
