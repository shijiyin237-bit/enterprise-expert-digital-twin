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
