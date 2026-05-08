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
