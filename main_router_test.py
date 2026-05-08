"""
Dynamic Persona Router - Sandbox Test Flow
Demonstrates the complete routing pipeline with mock data.
"""

import sys
from typing import List
from domain.models import CoreIdentity, DialogueSnippet, CurrentState
from services.state_tracker import StateAnalyzer
from services.behavioral_rag import DynamicRetriever


def create_mock_corpus() -> List[DialogueSnippet]:
    """
    Create a mock corpus with 10 dialogue snippets across different business intents.
    Simulates cleaned enterprise dialogue data.
    """
    return [
        # Tech Support snippets
        DialogueSnippet(
            user_input="你们的 API 接口突然报 500 错误了！",
            char_reply="收到，请提供您的 tenant_id，我立刻查看网关日志。",
            intent_tag="tech_support",
            scene_meta={"context": "system_failure"}
        ),
        DialogueSnippet(
            user_input="系统连不上数据库，怎么办？",
            char_reply="请检查数据库连接字符串，我来帮您诊断网络连通性。",
            intent_tag="tech_support",
            scene_meta={"context": "database_issue"}
        ),
        DialogueSnippet(
            user_input="代码部署后出现异常，需要回滚吗？",
            char_reply="先查看错误日志，如果是配置问题可以在线修复，否则建议回滚。",
            intent_tag="tech_support",
            scene_meta={"context": "deployment_issue"}
        ),
        DialogueSnippet(
            user_input="服务器宕机了，紧急情况！",
            char_reply="我已收到告警，正在启动备用服务器，预计2分钟内恢复。",
            intent_tag="tech_support",
            scene_meta={"context": "server_downtime"}
        ),
        
        # Sales Inquiry snippets
        DialogueSnippet(
            user_input="企业版的价格是多少？",
            char_reply="企业版根据用户规模定价，标准版5万/年，旗舰版20万/年。",
            intent_tag="sales_inquiry",
            scene_meta={"context": "pricing_inquiry"}
        ),
        DialogueSnippet(
            user_input="可以申请试用吗？",
            char_reply="当然可以，我们提供30天免费试用，需要您提供企业邮箱。",
            intent_tag="sales_inquiry",
            scene_meta={"context": "trial_request"}
        ),
        DialogueSnippet(
            user_input="有折扣吗？长期合作",
            char_reply="年付可享9折，3年付8折，另外还有定制化服务方案。",
            intent_tag="sales_inquiry",
            scene_meta={"context": "discount_negotiation"}
        ),
        
        # Casual/General snippets
        DialogueSnippet(
            user_input="你好，在吗？",
            char_reply="在的，我是企业助手，有什么可以帮您？",
            intent_tag="casual",
            scene_meta={"context": "greeting"}
        ),
        DialogueSnippet(
            user_input="谢谢你的帮助",
            char_reply="不客气，很高兴能帮到您，还有其他问题吗？",
            intent_tag="casual",
            scene_meta={"context": "acknowledgment"}
        ),
        DialogueSnippet(
            user_input="再见",
            char_reply="再见，祝您工作顺利！",
            intent_tag="casual",
            scene_meta={"context": "farewell"}
        ),
    ]


def assemble_dynamic_prompt(
    identity: CoreIdentity,
    state: CurrentState,
    few_shots: List[DialogueSnippet]
) -> str:
    """
    Assemble the final dynamic system prompt for LLM.
    Combines static identity rules with dynamic few-shot examples.
    """
    prompt_parts = [
        f"# Character Identity: {identity.name}",
        "\n## Static Rules (Immutable):",
    ]
    
    for rule in identity.static_rules:
        prompt_parts.append(f"- {rule}")
    
    prompt_parts.append("\n## Current Context:")
    prompt_parts.append(f"- User Intent: {state.user_intent}")
    prompt_parts.append(f"- Detected Intent: {state.detected_intent}")
    
    prompt_parts.append("\n## Few-Shot Examples (Dynamic):")
    for i, shot in enumerate(few_shots, 1):
        prompt_parts.append(f"\n### Example {i} [{shot.intent_tag}]:")
        prompt_parts.append(f"Client: {shot.user_input}")
        prompt_parts.append(f"Expert: {shot.char_reply}")
    
    prompt_parts.append("\n## Task:")
    prompt_parts.append("Based on the above examples and current context, respond to the user naturally while maintaining character consistency.")
    
    return "\n".join(prompt_parts)


def main():
    """
    Main test flow demonstrating the Dynamic Persona Router.
    """
    print("=" * 80)
    print("DYNAMIC PERSONA ROUTER - SANDBOX TEST")
    print("=" * 80)
    
    # Step 1: Initialize core identity
    print("\n[STEP 1] Initializing Core Identity...")
    identity = CoreIdentity(
        name="企业专家助手",
        static_rules=[
            "Always provide professional and accurate technical information",
            "Maintain enterprise-level communication standards",
            "Prioritize problem-solving and efficiency",
            "Never disclose sensitive company information"
        ]
    )
    print(f"  ✓ Identity: {identity.name}")
    print(f"  ✓ Static Rules: {len(identity.static_rules)} rules defined")
    
    # Step 2: Load mock corpus
    print("\n[STEP 2] Loading Mock Enterprise Corpus...")
    corpus = create_mock_corpus()
    print(f"  ✓ Loaded {len(corpus)} dialogue snippets")
    intent_distribution = {}
    for snippet in corpus:
        intent_distribution[snippet.intent_tag] = intent_distribution.get(snippet.intent_tag, 0) + 1
    print(f"  ✓ Intent Distribution: {intent_distribution}")
    
    # Step 3: Initialize services
    print("\n[STEP 3] Initializing Router Services...")
    state_analyzer = StateAnalyzer()
    retriever = DynamicRetriever()
    print("  ✓ State Analyzer initialized")
    print("  ✓ Dynamic Retriever initialized")
    
    # Step 4: Simulate user input
    test_input = "系统出现异常，需要技术支持"
    print(f"\n[STEP 4] Simulating User Input...")
    print(f"  User Input: \"{test_input}\"")
    
    # Step 5: Analyze state
    print(f"\n[STEP 5] State Analysis (Intent Probe)...")
    current_state = state_analyzer.analyze_input(test_input)
    print(f"  ✓ Detected Intent: {current_state.user_intent}")
    print(f"  ✓ Detected Business Intent: {current_state.detected_intent}")
    
    # Step 6: Retrieve few-shots
    print(f"\n[STEP 6] Dynamic Few-Shot Retrieval...")
    few_shots = retriever.retrieve_few_shots(current_state, corpus, top_k=3)
    print(f"  ✓ Retrieved {len(few_shots)} relevant snippets")
    for i, shot in enumerate(few_shots, 1):
        print(f"    [{i}] Intent: {shot.intent_tag} | Client: \"{shot.user_input[:20]}...\"")
    
    # Step 7: Assemble dynamic prompt
    print(f"\n[STEP 7] Assembling Dynamic System Prompt...")
    dynamic_prompt = assemble_dynamic_prompt(identity, current_state, few_shots)
    print(f"  ✓ Prompt assembled ({len(dynamic_prompt)} characters)")
    
    # Step 8: Display final prompt
    print("\n" + "=" * 80)
    print("FINAL DYNAMIC SYSTEM PROMPT FOR LLM:")
    print("=" * 80)
    print(dynamic_prompt)
    print("=" * 80)
    
    print("\n[✓] Test completed successfully!")
    print("\nSummary:")
    print(f"  - Input intent detected: {current_state.detected_intent}")
    print(f"  - Retrieved {len(few_shots)} {current_state.detected_intent}-themed examples")
    print(f"  - Dynamic prompt ready for LLM inference")


if __name__ == "__main__":
    main()
