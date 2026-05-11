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
                
                # [任务 1]：截留富文本遥测数据 - 构建高维度 trace_memories
                rag_memories = [result['text'] for result in rag_results]  # 供 Prompt 使用
                trace_memories = []  # 供遥测透传使用
                
                for result in rag_results:
                    try:
                        # 构建遥测字典，包含重排打分等硬核指标
                        telemetry_item = {
                            "text": result.get('text', ''),
                            "score": result.get('rerank_score', 0.0),  # 重排打分，默认0.0
                            "citation_source": result.get('metadata', {}).get('citation_source', '未知来源'),
                            "chunk_type": result.get('metadata', {}).get('chunk_type', '未知类型')
                        }
                        trace_memories.append(telemetry_item)
                    except Exception as e:
                        print(f"[!] 构建遥测数据失败: {e}，使用默认值")
                        trace_memories.append({
                            "text": result.get('text', ''),
                            "score": 0.0,
                            "citation_source": '未知来源',
                            "chunk_type": '未知类型'
                        })
                
                rag_metadata = [result['metadata'] for result in rag_results]
                print(f"[+] RAG 混合检索召回记忆条数：{len(rag_memories)}")
                print(f"[遥测透传] 已构建 {len(trace_memories)} 条富文本遥测数据")
                for i, (memory, meta, trace) in enumerate(zip(rag_memories, rag_metadata, trace_memories), 1):
                    timestamp = meta.get('start_timestamp', '未知时间')
                    score = trace.get('score', 0.0)
                    source = trace.get('citation_source', '未知来源')
                    print(f"    [{i}] 重排得分: {score:.3f} | 来源: {source} | 内容节选: {memory[:50]}...")
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
        
        # [核心节点]：返回包含企业级中间态数据的字典（含富文本遥测）
        return {
            "reply": reply,
            "business_intent": business_intent,
            "urgency_level": urgency_level,
            "retrieved_memories": trace_memories if 'trace_memories' in locals() else rag_memories,  # 优先返回富文本遥测
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
                
                # [核心节点]：金牌话术模板注入
                scripts = style.get('standard_scripts', [])
                if scripts:
                    prompt_parts.append("\n金牌话术模板（请在适当场景中自然使用）:")
                    for i, script in enumerate(scripts[:3], 1):  # 最多取3个话术模板
                        prompt_parts.append(f"{i}. {script}")
                    
                    # [核心节点]：话术使用护栏 - 防止模式坍塌
                    prompt_parts.append("\n【金牌话术使用红线】：")
                    prompt_parts.append("1. 严禁生硬堆砌！你必须且只能在当前的【业务意图】和【上下文语境】绝对契合时，才能使用上述话术。")
                    prompt_parts.append("2. 概率锁：在正常对话中，你有 80% 的概率完全不使用这些话术，必须使用你自己的自然语言回复。")
                    prompt_parts.append("3. 频次锁：每次回复【最多】只能使用 1 句金牌话术，绝对禁止在一大段话中连发多句模板！")
                    
                    print(f"[神经缝合] 成功注入 {len(scripts)} 个金牌话术模板 + 使用护栏")
            
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
