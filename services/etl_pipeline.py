"""
ETL 语料蒸馏与格式化微服务 - Map-Reduce 架构
基于 LLM 原生能力的智能语料清洗引擎
使用 Map-Reduce 切块提取机制，并发处理大规模语料

[核心节点]：多租户专家池架构 - ETL 流程自动对接专家入库和向量化
[核心节点]：一键炼丹流水线 - 数据自动嗅探、归一化、侧写、入库
"""

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
import openai
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import re
import difflib
from collections import Counter
from datetime import datetime

# [核心节点]：工业级容错库，指数退避重试机制
try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ImportError:
    print("[错误] 未找到 tenacity 库，请先安装: pip install tenacity")
    print("[提示] tenacity 用于网络抖动时的自动重试")
    sys.exit(1)

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from domain.models import DigitalTwinProfile, KnowledgeChunk
from services.expert_manager import ExpertManager, get_expert_manager
from services.vector_db_service import HybridSearchEngine

# 加载环境变量

load_dotenv()

# [核心节点]：全局 LLM 超时配置 - 防止网络阻塞导致假死
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

# [核心节点]：错误日志配置 - JSONDecodeError 自动记录
ERROR_LOG_DIR = Path("logs")
ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
ERROR_LOG_FILE = ERROR_LOG_DIR / "error_log.txt"

def log_error(error_type: str, error_msg: str, context: str = ""):
    """
    [核心节点]：错误日志记录函数
    将所有 JSONDecodeError 和其他异常记录到日志文件
    """
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] {error_type}: {error_msg}"
    if context:
        log_entry += f" | Context: {context}"
    log_entry += "\n"
    
    try:
        with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[!] 写入错误日志失败: {e}")

# 获取客户与专家身份配置
CLIENT_NAME = os.getenv("CLIENT_NAME")
EXPERT_NAME = os.getenv("EXPERT_NAME")

if not CLIENT_NAME or not EXPERT_NAME:
    raise ValueError("[致命错误] 环境变量 CLIENT_NAME 和 EXPERT_NAME 必须在 .env 中配置")


class SemanticChunker:
    """语义边界切片器 - 基于完整问答对切分语料，确保上下文完整性"""
    
    def __init__(self, qa_pairs_per_chunk: int = 10):
        """
        初始化语义边界切片器
        
        Args:
            qa_pairs_per_chunk: 每个 Chunk 包含的完整问答对数量（默认10对=20行）
        """
        self.qa_pairs_per_chunk = qa_pairs_per_chunk
        self.lines_per_chunk = qa_pairs_per_chunk * 2  # 每对问答 = 2行
    
    def load_and_chunk(self, file_path: str) -> List[List[Dict]]:
        """
        读取 JSONL 文件并按语义边界切分为多个 Chunk
        
        [核心节点]：语义边界切片 - 每10对完整问答(20行)为一个Chunk
        确保同一个问答对（患者和医生的对话）绝对不会被切断到两个不同的Chunk中
        
        Args:
            file_path: JSONL 文件路径
            
        Returns:
            Chunk 列表，每个 Chunk 是一个 List[Dict]
        """
        print(f"[+] 正在加载原始语料文件: {file_path}")
        
        corpus_data = []
        
        # 读取 JSONL 文件
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            corpus_data.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            print(f"[警告] 跳过无效JSON行: {e}")
                            continue
        except Exception as e:
            print(f"[致命拦截] 语料文件读取失败: {e}")
            print(f"[系统提示] 请检查文件路径是否正确，或文件格式是否为 JSONL")
            raise
        
        print(f"[+] 成功读取 {len(corpus_data)} 行原始数据")
        
        # [核心节点]：Token 成本熔断机制，强制拦截超大数据集进入 LLM 提纯层
        MAX_CORPUS_SIZE = 500  # 硬编码防线，超过 500 行直接截断
        if len(corpus_data) > MAX_CORPUS_SIZE:
            print(f"[!] Token 熔断触发：数据集大小 {len(corpus_data)} 超过阈值 {MAX_CORPUS_SIZE}，已强制截断")
            corpus_data = corpus_data[:MAX_CORPUS_SIZE]
            print(f"[+] 截断后数据量: {len(corpus_data)} 行")
        
        # [核心节点]：语义边界切片 - 按完整问答对切分，确保上下文完整性
        chunks = []
        for i in range(0, len(corpus_data), self.lines_per_chunk):
            chunk = corpus_data[i:i + self.lines_per_chunk]
            chunks.append(chunk)
        
        print(f"[+] 语义边界切片完成，共生成 {len(chunks)} 个 Chunk (每块 {self.qa_pairs_per_chunk} 对问答 = {self.lines_per_chunk} 行)")
        print(f"[+] 切片策略：确保完整问答对不会被切断，保留上下文语义完整性")
        return chunks


class LLMMapNode:
    """企业级知识提取器 - Map 阶段节点
    
    将原始对话语料转化为结构化的企业知识切片。
    严禁生成任何情绪标签、表情包占位符或闲聊内容。
    """
    
    def __init__(self, api_key: str = None, base_url: str = None):
        """
        初始化 OpenAI 客户端
        
        Args:
            api_key: OpenAI API 密钥
            base_url: OpenAI API 基础 URL
        """
        load_dotenv()
        
        api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        base_url = base_url or os.getenv("BASE_URL")
        
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("致命错误：未检测到真实的 API 密钥！")
        
        if not base_url:
            raise ValueError("致命错误：未检测到 BASE_URL！")
        
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = "Qwen/Qwen2.5-72B-Instruct"
    
    def _chunk_to_text(self, chunk: List[Dict]) -> str:
        """
        将 Chunk 转换为纯文本格式
        
        Args:
            chunk: Chunk 数据
            
        Returns:
            纯文本字符串
        """
        lines = []
        for item in chunk:
            speaker = item.get('speaker', '未知')
            content = item.get('content', '')
            timestamp = item.get('timestamp', '')
            lines.append(f"[{timestamp}] {speaker}: {content}")
        
        return "\n".join(lines)
    
    def _build_map_prompt(self, chunk_text: str, expert_id: str) -> str:
        """
        构建 Map 阶段的系统提示词
        
        输入：Chunk 的纯文本、专家ID
        输出：冷酷专业的企业级知识提取 Prompt
        
        原理：将原始对话转化为结构化的企业知识，严禁任何情绪渲染或幻觉生成
        
        [核心节点]：expert_id 注入 - 确保所有知识切片关联到正确的专家
        """
        return f"""你是一个冷酷、精确的企业级知识提取引擎。

【专家ID锚定】：
- 你的专家ID是：{expert_id}
- 所有提取的知识切片必须包含此 expert_id 字段

【角色自适应规则】：
- 不管原始语料里的 speaker 叫什么名字，你只需根据上下文逻辑识别角色
- 代表"买家/客户/用户"的发言，统一识别为 user_input
- 代表"金牌客服/专家/技术支持"的发言，统一识别为 char_reply
- 环境变量锚点：CLIENT_NAME={CLIENT_NAME} (客户)，EXPERT_NAME={EXPERT_NAME} (专家)

【绝对禁令】：
- 严禁生成任何情绪标签（如：开心、愤怒、委屈）
- 严禁保留表情包占位符（如 [猫咪大笑]）
- 严禁提取闲聊、互怼、日常问候等非业务内容
- 严禁编造或 hallucinate 任何不存在的信息
- 严禁保留特定姓名的硬编码判断

【容错性增强】：
- 如果语料中出现第三人称或系统消息，必须具备"物理剪枝"能力，将其剔除
- 如果无法明确判断角色，优先保留有专业解答内容的对话
- 如果对话不完整，可以跳过但不报错

【提取任务】：将对话转化为以下三种严格类型的企业知识切片：

1. QA_PAIR (标准问答)：客户提出业务问题，专家给出专业解答的完整对话
   - 必须包含明确的问题和对应的解决方案
   - 示例：客户询问 "API 如何认证？" 专家回答 "使用 Bearer Token..."

2. SOP_STEP (操作流程)：专家描述的标准作业程序、操作步骤或工作流程
   - 必须是可执行的步骤序列
   - 示例："第一步：登录管理后台；第二步：进入权限设置..."

3. BUSINESS_RULE (业务红线)：专家明确声明的合规边界、禁止事项或硬性约束
   - 必须包含 "不允许"、"禁止"、"必须"、"红线" 等关键词
   - 示例："严禁将客户数据存储在本地磁盘"

【输出规范】：严格对齐 KnowledgeChunk 数据契约，必须包含 expert_id 字段
- expert_id: 所属专家的唯一标识（从提示词参数注入）
- content: 知识切片的完整文本内容
- chunk_type: 必须是 "QA_PAIR"、"SOP_STEP" 或 "BUSINESS_RULE" 之一
- citation_source: 来源标注（格式：原始对话序号_时间戳）

以下是原始企业对话记录：
{chunk_text}

【致命红线】：输出的 JSON 字符串值中严禁包含未转义的换行符和双引号，必须是极其标准的 JSON 格式！

请严格以纯 JSON 格式输出，不要包含任何其他文字说明，格式如下：
{{
    "knowledge_chunks": [
        {{
            "expert_id": "{expert_id}",
            "content": "知识切片的完整文本",
            "chunk_type": "QA_PAIR",
            "citation_source": "chunk_001_2024-01-20"
        }}
    ]
}}

【输出要求】：
1. 每个知识切片必须包含 "expert_id": "{expert_id}" 字段
2. 所有字符串值必须正确转义换行符和双引号
3. 严禁在 JSON 中包含注释或额外文字说明
4. 必须是有效的 JSON 格式，可直接被 json.loads() 解析"""
    
    def _clean_and_parse_json(self, text: str) -> dict | list:
        """
        [核心节点：物理剥壳机]：Markdown Stripper - 精准提取 JSON 实体
        
        输入：可能包含 Markdown 包装、废话前缀的 LLM 返回文本
        输出：纯净的 Python dict/list 对象
        
        逻辑：
        1. 物理去除文本首尾的 Markdown 代码块标记（```json, ```, ```jsonl）
        2. 寻找第一个 { 或 [，以及最后一个 } 或 ]，截取出来解析
        3. 无论大模型在前面加了多少废话，都能精准命中 JSON 实体
        """
        import re
        
        # [物理剥壳] 正在清理 Markdown 标签...
        print("[物理剥壳] 正在清理 Markdown 标签...")
        
        # 步骤 1：去除首尾 Markdown 代码块标记
        text = re.sub(r'^```[a-zA-Z]*\n*', '', text.strip())
        text = re.sub(r'\n*```\s*$', '', text.strip())
        text = re.sub(r'^```[a-zA-Z]*\s*', '', text.strip())
        
        # 步骤 2：寻找 JSON 实体的物理边界
        first_brace = text.find('{')
        first_bracket = text.find('[')
        
        # 确定起始位置
        if first_brace == -1 and first_bracket == -1:
            raise ValueError("[物理剥壳失败] 未找到 JSON 起始标记 { 或 [")
        elif first_brace == -1:
            start = first_bracket
        elif first_bracket == -1:
            start = first_brace
        else:
            start = min(first_brace, first_bracket)
        
        # 确定结束位置（从后往前找）
        last_brace = text.rfind('}')
        last_bracket = text.rfind(']')
        
        if last_brace == -1 and last_bracket == -1:
            raise ValueError("[物理剥壳失败] 未找到 JSON 结束标记 } 或 ]")
        elif last_brace == -1:
            end = last_bracket
        elif last_bracket == -1:
            end = last_brace
        else:
            end = max(last_brace, last_bracket)
        
        # 步骤 3：截取纯净的 JSON 文本
        json_text = text[start:end+1]
        
        print(f"[物理剥壳] 成功提取 JSON 实体，长度: {len(json_text)} 字符")
        
        # 步骤 4：解析 JSON
        try:
            result = json.loads(json_text)
            print("[物理剥壳] JSON 解析成功！")
            return result
        except json.JSONDecodeError as e:
            raise ValueError(f"[物理剥壳] JSON 解析失败: {e}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def extract_chunk(self, chunk: List[Dict], chunk_index: int, expert_id: str) -> List[KnowledgeChunk]:
        """
        处理单个 Chunk，提取企业级知识切片
        
        输入：Chunk 数据和索引、专家ID
        输出：KnowledgeChunk 列表
        
        原理：调用轻量级 LLM 将原始对话转化为结构化企业知识
        
        [核心节点]：工业级容错 - 网络抖动时自动进行 3 次指数退避重试
        [核心节点]：expert_id 注入 - 所有知识切片必须关联到指定专家
        """
        try:
            # 转换为纯文本
            chunk_text = self._chunk_to_text(chunk)
            
            # [核心节点]：构建企业级知识提取 Prompt（注入 expert_id）
            prompt = self._build_map_prompt(chunk_text, expert_id)
            
            # [核心节点]：调用轻量级 LLM 进行知识提取（肺活量 8192 防止 Token 腰斩）
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "开始提取"}
                ],
                temperature=0.1,
                max_tokens=8192,
                response_format={"type": "json_object"}
            )

            # 解析结果
            result_text = response.choices[0].message.content
            print(f"[调试] 切片 {chunk_index + 1} 返回内容前 200 字符: {result_text[:200]}")

            # [核心节点：物理剥壳 + 自省纠错]：双重保障机制
            result_dict = None
            try:
                # 第一次尝试：使用物理剥壳机直接解析
                result_dict = self._clean_and_parse_json(result_text)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[致命拦截] 切片 {chunk_index + 1} JSON 解析失败，已触发大模型自纠错...")
                print(f"[自省纠错] 发起第二次 LLM 请求修复非法 JSON...")

                # [核心节点：加固自纠错 Prompt] - 严禁 Markdown 包装
                correction_prompt = f"""你刚才生成的 JSON 引发了错误：{str(e)}。请修复它！
【绝对红线】：严禁使用 Markdown 代码块包围！严禁输出 ```json！直接以 {{ 或 [ 开头输出纯净的 JSON！

需要修复的内容：
{result_text}"""

                try:
                    correction_response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": "你是一个 JSON 修复专家。直接输出修复后的合法 JSON，不要任何解释，不要 Markdown 包装。"},
                            {"role": "user", "content": correction_prompt}
                        ],
                        temperature=0.0,
                        max_tokens=8192,
                        response_format={"type": "json_object"}
                    )

                    corrected_text = correction_response.choices[0].message.content
                    print(f"[自省纠错] 修复后内容前 200 字符: {corrected_text[:200]}")

                    # 尝试解析修复后的 JSON（再次使用物理剥壳机）
                    try:
                        result_dict = self._clean_and_parse_json(corrected_text)
                        print(f"[自省纠错] JSON 修复成功！切片 {chunk_index + 1} 数据已恢复")
                    except (json.JSONDecodeError, ValueError) as e2:
                        print(f"[致命拦截] 切片 {chunk_index + 1} 自纠错失败，跳过当前切片: {e2}")
                        log_error("JSON_SELF_CORRECTION_FAILED", str(e2), f"LLMMapNode.chunk_{chunk_index + 1}")
                        return []

                except Exception as correction_error:
                    print(f"[致命拦截] 切片 {chunk_index + 1} 纠错请求失败: {correction_error}")
                    log_error("JSON_CORRECTION_REQUEST_FAILED", str(correction_error), f"LLMMapNode.chunk_{chunk_index + 1}")
                    return []
            
            # 确保 result_dict 包含 knowledge_chunks 字段
            if isinstance(result_dict, dict):
                if 'knowledge_chunks' in result_dict:
                    result_dict = result_dict['knowledge_chunks']
                elif 'data' in result_dict:
                    result_dict = result_dict['data']
                elif 'results' in result_dict:
                    result_dict = result_dict['results']
                else:
                    # 可能是其他格式，取第一个列表值
                    values = list(result_dict.values())
                    if values and isinstance(values[0], list):
                        result_dict = values[0]
                    else:
                        print(f"[!] 切片 {chunk_index + 1} 返回格式异常，跳过")
                        return []
            
            if not isinstance(result_dict, list):
                print(f"[!] 切片 {chunk_index + 1} 返回不是数组，跳过")
                return []
            
            # [核心节点]：利用 Pydantic 强校验知识切片数据，强制注入 expert_id
            knowledge_chunks = []
            for item in result_dict:
                try:
                    # [核心节点]：强制赋值 expert_id，确保数据契约完整
                    chunk = KnowledgeChunk(
                        expert_id=expert_id,  # [核心节点]：强制注入 expert_id
                        content=item.get('content', ''),
                        chunk_type=item.get('chunk_type', 'QA_PAIR'),
                        citation_source=item.get('citation_source', f"chunk_{chunk_index + 1}_unknown")
                    )
                    knowledge_chunks.append(chunk)
                except Exception as validation_error:
                    print(f"[!] 切片 {chunk_index + 1} 数据校验失败: {validation_error}，跳过此项")
                    continue
            
            print(f"[知识提取] 切片 {chunk_index + 1} 完成... 提取到 {len(knowledge_chunks)} 条企业级知识...")
            return knowledge_chunks
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[!] 切片 {chunk_index + 1} 处理失败: {error_type}: {error_msg}")
            
            # [核心节点]：网络错误特殊提示
            if "ConnectError" in error_type or "Connection" in error_msg:
                print(f"[!] 网络连接错误，请检查：")
                print(f"    1. BASE_URL 配置是否正确")
                print(f"    2. 网络是否需要代理设置")
                print(f"    3. 运行 python debug_api.py 进行诊断")
            
            return []


class LLMJudgeReduce:
    """首席知识官 - Reduce 阶段节点
    
    作为企业级知识审核中枢，审查并合并所有知识切片。
    去除重复的问答，解决相互冲突的业务规则。
    """
    
    def __init__(self, api_key: str = None, base_url: str = None):
        """
        初始化 OpenAI 客户端
        
        Args:
            api_key: OpenAI API 密钥
            base_url: OpenAI API 基础 URL
        """
        load_dotenv()
        
        api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        base_url = base_url or os.getenv("BASE_URL")
        
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("致命错误：未检测到真实的 API 密钥！")
        
        if not base_url:
            raise ValueError("致命错误：未检测到 BASE_URL！")
        
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = "Qwen/Qwen2.5-72B-Instruct"
    
    def _build_reduce_prompt(self, all_chunks: List[KnowledgeChunk], expert_id: str) -> str:
        """
        构建 Reduce 阶段的系统提示词
        
        输入：所有提取的知识切片、专家ID
        输出：首席知识官审查 Prompt
        
        原理：作为知识审核中枢，输出高纯度、无重复、无冲突的知识数组
        
        [核心节点]：expert_id 注入 - 确保审查后的知识切片关联到正确的专家
        """
        # 取前 300 条避免 token 超限
        sample_chunks = all_chunks[:300]
        
        chunk_text = ""
        for i, chunk in enumerate(sample_chunks, 1):
            chunk_text += f"\n切片 {i} [{chunk.chunk_type} | 来源: {chunk.citation_source}]:\n"
            chunk_text += f"{chunk.content}\n"
        
        return f"""你是一个冷酷、精确的首席知识官 (Chief Knowledge Officer)。你的职责是审查并优化企业知识库。

【专家ID锚定】：
- 你的专家ID是：{expert_id}
- 所有审查后的知识切片必须包含此 expert_id 字段

【核心任务】：
1. 去除重复的问答：如果多个切片描述相同的问题和答案，只保留最完整的一条
2. 解决冲突的业务规则：如果两条规则相互矛盾，优先保留更严格、更保守的那条
3. 合并同类型的 SOP 步骤：将分散的步骤整合为完整的操作流程
4. 剔除所有非业务内容：闲聊、表情包、情绪表达一律删除

【输入数据类型】：
- QA_PAIR: 标准问答，包含客户问题和专家解答
- SOP_STEP: 操作流程，包含可执行的步骤序列
- BUSINESS_RULE: 业务红线，包含合规边界和禁止事项

【输出规范】：严格对齐 KnowledgeChunk 数据契约，必须包含 expert_id 字段
- expert_id: 所属专家的唯一标识（使用提供的 expert_id: {expert_id}）
- content: 审查后的知识切片内容
- chunk_type: "QA_PAIR"、"SOP_STEP" 或 "BUSINESS_RULE"
- citation_source: 来源标注

以下是所有知识切片：
{chunk_text}

【致命红线】：输出的 JSON 字符串值中严禁包含未转义的换行符和双引号，必须是极其标准的 JSON 格式！

请严格以纯 JSON 格式输出，不要包含任何其他文字说明，格式如下：
{{
    "knowledge_chunks": [
        {{
            "expert_id": "{expert_id}",
            "content": "审查后的知识切片内容",
            "chunk_type": "QA_PAIR",
            "citation_source": "来源标注"
        }}
    ]
}}

【输出要求】：
1. 每个知识切片必须包含 "expert_id": "{expert_id}" 字段
2. 所有字符串值必须正确转义换行符和双引号
3. 严禁在 JSON 中包含注释或额外文字说明
4. 必须是有效的 JSON 格式，可直接被 json.loads() 解析"""
    
    def _clean_and_parse_json(self, text: str) -> dict | list:
        """
        [核心节点：物理剥壳机]：Markdown Stripper - 精准提取 JSON 实体
        
        输入：可能包含 Markdown 包装、废话前缀的 LLM 返回文本
        输出：纯净的 Python dict/list 对象
        
        逻辑：
        1. 物理去除文本首尾的 Markdown 代码块标记（```json, ```, ```jsonl）
        2. 寻找第一个 { 或 [，以及最后一个 } 或 ]，截取出来解析
        3. 无论大模型在前面加了多少废话，都能精准命中 JSON 实体
        """
        import re
        
        # [物理剥壳] 正在清理 Markdown 标签...
        print("[物理剥壳] 正在清理 Markdown 标签...")
        
        # 步骤 1：去除首尾 Markdown 代码块标记
        text = re.sub(r'^```[a-zA-Z]*\n*', '', text.strip())
        text = re.sub(r'\n*```\s*$', '', text.strip())
        text = re.sub(r'^```[a-zA-Z]*\s*', '', text.strip())
        
        # 步骤 2：寻找 JSON 实体的物理边界
        first_brace = text.find('{')
        first_bracket = text.find('[')
        
        # 确定起始位置
        if first_brace == -1 and first_bracket == -1:
            raise ValueError("[物理剥壳失败] 未找到 JSON 起始标记 { 或 [")
        elif first_brace == -1:
            start = first_bracket
        elif first_bracket == -1:
            start = first_brace
        else:
            start = min(first_brace, first_bracket)
        
        # 确定结束位置（从后往前找）
        last_brace = text.rfind('}')
        last_bracket = text.rfind(']')
        
        if last_brace == -1 and last_bracket == -1:
            raise ValueError("[物理剥壳失败] 未找到 JSON 结束标记 } 或 ]")
        elif last_brace == -1:
            end = last_bracket
        elif last_bracket == -1:
            end = last_brace
        else:
            end = max(last_brace, last_bracket)
        
        # 步骤 3：截取纯净的 JSON 文本
        json_text = text[start:end+1]
        
        print(f"[物理剥壳] 成功提取 JSON 实体，长度: {len(json_text)} 字符")
        
        # 步骤 4：解析 JSON
        try:
            result = json.loads(json_text)
            print("[物理剥壳] JSON 解析成功！")
            return result
        except json.JSONDecodeError as e:
            raise ValueError(f"[物理剥壳] JSON 解析失败: {e}")
    
    def judge_and_reduce(self, all_chunks: List[KnowledgeChunk], expert_id: str) -> List[KnowledgeChunk]:
        """
        [知识压缩轨] 通用的分批压缩架构 - 解决 Token 爆炸
        
        输入：所有提取的知识切片、专家ID
        输出：经过首席知识官审查后的高纯度 KnowledgeChunk 列表
        
        原理：
            1. [物理去重]：使用 difflib 进行模糊语义去重，剔除高度重复内容
            2. [分批打包]：无视数据类型，强制按 MAX_BATCH_SIZE=40 切分
            3. [循环提纯]：遍历每个 Batch 独立调用大模型进行知识压缩
            4. [合并返回]：将所有 Batch 处理后的合法 JSON 数组合并返回
        
        [核心节点]：expert_id 注入 - 确保所有审查后的知识切片关联到指定专家
        """
        original_count = len(all_chunks)
        print(f"\n[知识压缩轨] 开始提纯 {original_count} 条知识切片...")
        
        # [0 数据物理熔断锁]
        if original_count == 0:
            print(f"[知识压缩轨] 0 数据物理熔断锁触发，返回空列表")
            return []
        
        try:
            # [任务 1]：模糊语义去重 (Fuzzy Semantic Deduplication)
            print(f"[物理去重] 正在执行模糊语义去重，阈值 0.85...")
            deduplicated_chunks = []
            
            for i, current_chunk in enumerate(all_chunks):
                current_text = current_chunk.content
                is_duplicate = False
                
                # 与已保留的切片进行相似度比对
                for existing_chunk in deduplicated_chunks:
                    similarity = difflib.SequenceMatcher(None, current_text, existing_chunk.content).ratio()
                    if similarity > 0.85:  # 熔断阈值
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    deduplicated_chunks.append(current_chunk)
            
            deduplicated_count = len(deduplicated_chunks)
            print(f"[物理去重] 发现高度重复切片，已从 {original_count} 压缩至 {deduplicated_count} 条。")
            
            # [任务 2]：分批打包 (Batching) - 无视数据类型强制切分
            MAX_BATCH_SIZE = 40
            total_batches = (deduplicated_count + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
            
            print(f"[知识压缩轨] 检测到 {deduplicated_count} 条切片，将分为 {total_batches} 批处理（每批最多 {MAX_BATCH_SIZE} 条）")
            
            all_final_chunks = []
            
            # [任务 3]：循环提纯 - 遍历每个 Batch 独立调用大模型
            for batch_idx in range(total_batches):
                start_idx = batch_idx * MAX_BATCH_SIZE
                end_idx = min(start_idx + MAX_BATCH_SIZE, deduplicated_count)
                batch_chunks = deduplicated_chunks[start_idx:end_idx]
                
                print(f"[知识压缩轨] 正在提纯第 {batch_idx + 1}/{total_batches} 批数据，当前批次 {len(batch_chunks)} 条...")
                
                try:
                    # 调用 LLM 处理当前批次
                    batch_final_chunks = self._process_single_batch(batch_chunks, expert_id)
                    all_final_chunks.extend(batch_final_chunks)
                    
                    print(f"[知识压缩轨] 第 {batch_idx + 1} 批提纯完成，精选出 {len(batch_final_chunks)} 条")
                except Exception as batch_error:
                    # [全局容错]：单批次失败只丢弃该批次，严禁中断整个流程
                    print(f"[!] 批次 {batch_idx + 1} 处理失败，跳过该批次: {batch_error}")
                    continue
            
            print(f"[知识压缩轨] 所有批次处理完成，最终精选 {len(all_final_chunks)} 条高纯度知识")
            return all_final_chunks
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[!] 首席知识官审查失败: {error_type}: {error_msg}")
            
            # [核心节点]：网络错误特殊提示
            if "ConnectError" in error_type or "Connection" in error_msg:
                print(f"[!] 网络连接错误，请检查：")
                print(f"    1. BASE_URL 配置是否正确")
                print(f"    2. 网络是否需要代理设置")
                print(f"    3. 运行 python debug_api.py 进行诊断")
            
            return all_chunks[:200]  # 降级返回前 200 条
    
    def _process_single_batch(self, batch_chunks: List[KnowledgeChunk], expert_id: str) -> List[KnowledgeChunk]:
        """
        处理单个批次的知识切片
        
        输入：批次知识切片、专家ID
        输出：该批次经过 LLM 审查后的精选切片
        """
        try:
            # [核心节点]：构建首席知识官审查 Prompt（注入 expert_id + 强力压缩指令）
            prompt = self._build_reduce_prompt(batch_chunks, expert_id)
            
            # [强化指令]：无情的知识压缩机
            prompt += "\n\n【强化指令】：你是一个无情的知识压缩机。请将这批对话中的客观知识提取为纯粹的 QA 或 SOP。如果发现语义完全重复的内容，必须合并为一条！剔除所有无关的寒暄废话。"
            
            # [核心节点]：调用大模型进行知识审查（肺活量 8192 防止 Token 腰斩）
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "开始审查"}
                ],
                temperature=0.1,
                max_tokens=8192,
                response_format={"type": "json_object"}
            )
            
            # 解析结果
            result_text = response.choices[0].message.content
            print(f"[调试] 批次 Reduce 返回内容前 200 字符: {result_text[:200]}")
            
            # [核心节点：物理剥壳机]：精准提取 JSON 实体，无论 LLM 加多少废话
            try:
                result_dict = self._clean_and_parse_json(result_text)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[致命拦截] 批次 Reduce 阶段 JSON 解析失败: {e}")
                print(f"[物理剥壳] 尝试备用方案，返回原始批次数据...")
                log_error("JSON_CLEAN_PARSE_FAILED", str(e), "LLMJudgeReduce")
                return batch_chunks  # 降级返回当前批次原始数据
            
            # 提取 knowledge_chunks 字段
            if isinstance(result_dict, dict):
                if 'knowledge_chunks' in result_dict:
                    result_dict = result_dict['knowledge_chunks']
                elif 'data' in result_dict:
                    result_dict = result_dict['data']
                elif 'results' in result_dict:
                    result_dict = result_dict['results']
                else:
                    # 可能是其他格式，取第一个列表值
                    values = list(result_dict.values())
                    if values and isinstance(values[0], list):
                        result_dict = values[0]
                    else:
                        print(f"[!] 批次 Reduce 返回格式异常，使用原始批次数据")
                        return batch_chunks
            
            if not isinstance(result_dict, list):
                print(f"[!] 批次 Reduce 返回不是数组，使用原始批次数据")
                return batch_chunks
            
            # [核心节点]：利用 Pydantic 强校验审查后的知识切片，强制注入 expert_id
            final_chunks = []
            for item in result_dict:
                try:
                    # [核心节点]：强制赋值 expert_id，确保数据契约完整
                    chunk = KnowledgeChunk(
                        expert_id=expert_id,  # [核心节点]：强制注入 expert_id
                        content=item.get('content', ''),
                        chunk_type=item.get('chunk_type', 'QA_PAIR'),
                        citation_source=item.get('citation_source', 'ck_reviewed')
                    )
                    final_chunks.append(chunk)
                except Exception as validation_error:
                    print(f"[!] 批次知识切片校验失败: {validation_error}，跳过此项")
                    continue
            
            return final_chunks
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[!] 批次处理失败: {error_type}: {error_msg}")
            
            # [核心节点]：网络错误特殊提示
            if "ConnectError" in error_type or "Connection" in error_msg:
                print(f"[!] 网络连接错误，请检查：")
                print(f"    1. BASE_URL 配置是否正确")
                print(f"    2. 网络是否需要代理设置")
                print(f"    3. 运行 python debug_api.py 进行诊断")
            
            return batch_chunks  # 降级返回当前批次原始数据


class DigitalTwinDistiller:
    """数字孪生侧写师 - 从企业语料中提取专家画像
    
    废弃情感克隆逻辑，专注于企业级专家数字孪生画像构建。
    严禁"峰终定律"、"高光记忆"、"傲娇"等情感类词汇。
    """
    
    def __init__(self, api_key: str = None, base_url: str = None):
        """
        初始化 OpenAI 客户端
        
        Args:
            api_key: OpenAI API 密钥
            base_url: OpenAI API 基础 URL
        """
        load_dotenv()
        
        api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        base_url = base_url or os.getenv("BASE_URL")
        
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("致命错误：未检测到真实的 API 密钥！")
        
        if not base_url:
            raise ValueError("致命错误：未检测到 BASE_URL！")
        
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = "Qwen/Qwen2.5-72B-Instruct"
    
    def _build_distillation_prompt(self, corpus: List[KnowledgeChunk], expert_id: str) -> str:
        """
        构建用于数字孪生侧写的提示词
        
        输入：完整企业知识语料库、专家ID
        输出：冷酷专业的企业专家画像提取 Prompt
        
        原理：从企业对话中提取专家的专业领域、沟通风格、业务红线
        
        [核心节点]：expert_id 注入 - 确保专家画像包含正确的专家标识
        """
        # 提取前 50 条知识切片作为样本
        sample_chunks = corpus[:50]
        
        knowledge_text = ""
        for i, chunk in enumerate(sample_chunks, 1):
            knowledge_text += f"\n切片 {i} [{chunk.chunk_type}]:\n"
            knowledge_text += f"{chunk.content}\n"
        
        system_prompt = f"""你是一个冷酷、精确的企业级专家画像侧写引擎。

【专家ID锚定】：
- 你的专家ID是：{expert_id}
- 必须在输出 JSON 中包含此 expert_id 字段

【角色自适应规则】：
- 不管原始语料里的 speaker 叫什么名字，你只需根据上下文逻辑识别专家角色
- 环境变量锚点：CLIENT_NAME={os.getenv("CLIENT_NAME")} (客户)，EXPERT_NAME={os.getenv("EXPERT_NAME")} (专家)
- 从对话内容中推断专家的真实身份，而不是依赖 speaker 字段的名称

【绝对禁令】：
- 严禁生成任何情绪标签（如：温柔、严厉、幽默）
- 严禁编造或 hallucinate 任何不存在的信息
- 严禁保留对话中的具体姓名作为专家名称

【提取任务】：从企业对话中蒸馏数字孪生专家画像，严格对齐 DigitalTwinProfile 数据契约

1. expert_id (专家唯一标识)
   - 必须使用提供的专家ID: {expert_id}
   - 严禁修改或生成其他ID

2. expert_name (专家姓名/代号)
   - 根据对话内容和专业能力推断，而非 speaker 字段
   - 示例："金牌架构师"、"资深法务顾问"、"售前金牌销售"

3. domain_expertise (擅长的专业领域)
   - 描述该专家的核心业务能力和专业边界
   - 示例："云计算架构设计与故障排查"、"企业合规与合同审查"

4. communication_style (沟通风格)
   - 描述专家的沟通方式和专业话术特征
   - 字段包括：tone（语气风格）、response_pattern（响应模式）、key_phrases（高频专业表达）、standard_scripts（金牌话术模板）
   - 示例：{{"tone": "严谨专业", "response_pattern": "先诊断后解决", "key_phrases": ["建议", "必须", "严禁"], "standard_scripts": ["建议您尽快带孩子去医院做进一步检查", "这款目前库存紧张，建议先拍下锁单"]}}
   - [核心节点]：即便语料很少，也要根据现有对话总结出语气特征
   
【金牌话术提取指令】：你必须从语料中提取出该专家反复使用的、具有行业特征的 3-5 句"金牌话术模板"（如：安抚话术、逼单话术、免责话术）。
- 这些话术必须是专家的【原话原句】，不能是你概括的短语！
- 如果语料中没有明显重复的句子，请提取最具专业代表性的完整句子。

5. business_redlines (业务红线)
   - 专家明确声明的合规边界、禁止事项、硬性约束
   - 必须包含"禁止"、"不允许"、"红线"、"严禁"等关键词
   - 示例："绝不承诺未发布的特性"、"严禁将客户数据存储在本地磁盘"

6. golden_few_shots (金牌示例对话)
   - 从对话中提取的典型用户提问和专家回答示例
   - 用于大模型 Few-Shot 模仿，恢复语气模仿能力
   - 格式：[{{"user_input": "用户提问", "expert_reply": "专家回答"}}]
   - 示例：[{{"user_input": "API如何认证？", "expert_reply": "请使用Bearer Token进行认证..."}}]
   
【示例提取绝对红线】：必须像外科医生一样拆分原始对话！
- user_input：只允许填入客户/患者的原话，绝对禁止混入专家的回答！
- expert_reply：只允许填入专家/医生的原话，绝对禁止混入客户的提问！
- 严禁两者内容重复！必须保留专家的真实语气词和口头禅！

7. supported_intents (租户专属业务意图)
   - [核心节点]：根据传入的知识切片，总结出该专家日常处理的 3-5 个核心业务意图
   - 意图必须是专家实际处理的业务场景（如：病理问诊、用药指导、肥胖评估、检查解读）
   - 最后一个意图必须是兜底意图（如："其他咨询"、"闲聊兜底"、"通用问答"）
   - 格式：["意图1", "意图2", "意图3", "兜底意图"]
   - 示例：["病理问诊", "用药指导", "检查报告解读", "其他咨询"]
   - [核心节点]：意图名称要简洁专业，体现租户业务特色，严禁通用意图如"技术支持"

8. reasoning_logic (专家业务推理SOP)
   - 根据对话反向推导出的该专家处理业务的"通用思考链路"（3-5步）。
   - 必须体现专家的深层业务逻辑，而不是表层对话。
   - 示例：["第一步：倾听并共情用户的情绪", "第二步：排查是否存在物理损坏或操作不当", "第三步：明确给出退换货或维修的终极方案"]

【提取示例红线】：在提取 golden_few_shots 时，必须像外科手术一样精确分离！

- 正确示例：{{"user_input": "孩子发烧39度怎么办？", "expert_reply": "建议立即物理降温并就医"}}
- 错误示例（严禁）：{{"user_input": "用户问孩子发烧怎么办，专家回答建议就医", "expert_reply": ""}} —— 这是严重错误！
- 错误示例（严禁）：{{"user_input": "孩子发烧39度怎么办？建议立即物理降温", "expert_reply": "孩子发烧39度怎么办？建议立即物理降温"}} —— 这是复读机错误！

【输出规范】：严格对齐 DigitalTwinProfile 数据契约，输出纯 JSON
- 必须包含 DigitalTwinProfile 模型定义的所有字段，缺一不可
- 必须包含 expert_id 字段，使用值: {expert_id}
- 必须包含 golden_few_shots 字段，用于恢复语气模仿能力
- 必须包含 supported_intents 字段，且至少包含 3 个意图（含兜底）

【致命红线】：输出的 JSON 字符串值中严禁包含未转义的换行符和双引号，必须是极其标准的 JSON 格式！

以下是企业对话记录：
{knowledge_text}

请严格以纯 JSON 格式输出，不要包含任何其他文字说明，格式如下：
{{
    "expert_id": "{expert_id}",
    "expert_name": "专家姓名/代号",
    "domain_expertise": "擅长的专业领域描述",
    "communication_style": {{
        "tone": "语气风格",
        "response_pattern": "响应模式",
        "key_phrases": ["高频专业表达1", "高频专业表达2"],
        "standard_scripts": ["金牌话术模板1", "金牌话术模板2", "金牌话术模板3"]
    }},
    "business_redlines": ["业务红线1", "业务红线2"],
    "reasoning_logic": ["第一步：倾听并共情用户的情绪", "第二步：排查是否存在物理损坏或操作不当", "第三步：明确给出退换货或维修的终极方案"],
    "golden_few_shots": [
        {{
            "user_input": "典型用户提问（必须是客户原话，严禁包含专家回答）",
            "expert_reply": "专家标准回答（必须是专家原话，严禁与user_input重复）"
        }}
    ],
    "supported_intents": ["意图1", "意图2", "意图3", "闲聊兜底"]
}}


【输出要求】：
1. 必须包含 "expert_id": "{expert_id}" 字段
2. 必须包含 "golden_few_shots" 数组字段，user_input 和 expert_reply 必须分离
3. 必须包含 "supported_intents" 数组字段，至少 3 个意图且包含兜底意图
4. 必须包含 "reasoning_logic" 数组字段，至少 3 步推理步骤
5. 所有字符串值必须正确转义换行符和双引号
6. 严禁在 JSON 中包含注释或额外文字说明
7. 必须是有效的 JSON 格式，可直接被 json.loads() 解析"""

        return system_prompt
    
    def _clean_and_parse_json(self, text: str) -> dict | list:
        """
        [核心节点：物理剥壳机]：Markdown Stripper - 精准提取 JSON 实体
        
        输入：可能包含 Markdown 包装、废话前缀的 LLM 返回文本
        输出：纯净的 Python dict/list 对象
        
        逻辑：
        1. 物理去除文本首尾的 Markdown 代码块标记（```json, ```, ```jsonl）
        2. 寻找第一个 { 或 [，以及最后一个 } 或 ]，截取出来解析
        3. 无论大模型在前面加了多少废话，都能精准命中 JSON 实体
        """
        import re
        
        # [物理剥壳] 正在清理 Markdown 标签...
        print("[物理剥壳] 正在清理 Markdown 标签...")
        
        # 步骤 1：去除首尾 Markdown 代码块标记
        text = re.sub(r'^```[a-zA-Z]*\n*', '', text.strip())
        text = re.sub(r'\n*```\s*$', '', text.strip())
        text = re.sub(r'^```[a-zA-Z]*\s*', '', text.strip())
        
        # 步骤 2：寻找 JSON 实体的物理边界
        first_brace = text.find('{')
        first_bracket = text.find('[')
        
        # 确定起始位置
        if first_brace == -1 and first_bracket == -1:
            raise ValueError("[物理剥壳失败] 未找到 JSON 起始标记 { 或 [")
        elif first_brace == -1:
            start = first_bracket
        elif first_bracket == -1:
            start = first_brace
        else:
            start = min(first_brace, first_bracket)
        
        # 确定结束位置（从后往前找）
        last_brace = text.rfind('}')
        last_bracket = text.rfind(']')
        
        if last_brace == -1 and last_bracket == -1:
            raise ValueError("[物理剥壳失败] 未找到 JSON 结束标记 } 或 ]")
        elif last_brace == -1:
            end = last_bracket
        elif last_bracket == -1:
            end = last_brace
        else:
            end = max(last_brace, last_bracket)
        
        # 步骤 3：截取纯净的 JSON 文本
        json_text = text[start:end+1]
        
        print(f"[物理剥壳] 成功提取 JSON 实体，长度: {len(json_text)} 字符")
        
        # 步骤 4：解析 JSON
        try:
            result = json.loads(json_text)
            print("[物理剥壳] JSON 解析成功！")
            return result
        except json.JSONDecodeError as e:
            raise ValueError(f"[物理剥壳] JSON 解析失败: {e}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def distill_digital_twin(self, corpus: List[KnowledgeChunk], expert_id: str) -> DigitalTwinProfile:
        """
        [灵魂侧写轨] 独立采样与反复读机架构 - 解决示例复读机
        
        输入：完整企业知识语料库、专家ID
        输出：DigitalTwinProfile 对象
        
        原理：
            1. [独立采样]：直接传入 Map 阶段提取的原汁原味切片，保证语气保真度
            2. [斩断复读幻觉]：针对 golden_few_shots 提取加入绝对红线
            3. [数字孪生侧写]：对接 DigitalTwinProfile 数据契约
        
        [核心节点]：工业级容错 - 网络抖动时自动进行 3 次指数退避重试
        [核心节点]：expert_id 注入 - 确保专家画像包含正确的专家标识
        """
        # [任务 1]：独立采样 - 直接传入 Map 阶段原汁原味切片
        print(f"[灵魂侧写轨] 正在进行独立采样，抽取最具代表性的 {min(50, len(corpus))} 条原汁原味切片...")
        
        # 随机采样 50 条原汁原味切片（不使用 Reduce 压缩后的干瘪数据）
        import random
        sample_size = min(50, len(corpus))
        sampled_corpus = random.sample(corpus, sample_size) if len(corpus) > sample_size else corpus
        
        print(f"[灵魂侧写轨] 已采样 {len(sampled_corpus)} 条原汁原味切片，保证语气保真度")
        
        # [核心节点]：构建数字孪生侧写 Prompt（注入 expert_id）
        prompt = self._build_distillation_prompt(sampled_corpus, expert_id)
        
        try:
            # [核心节点]：调用大模型进行专家画像侧写（肺活量 8192 防止 Token 腰斩）
            print(f"[-] 正在调用大模型进行数字孪生侧写...")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "开始分析"}
                ],
                temperature=0.1,
                max_tokens=8192,
                response_format={"type": "json_object"}
            )
            
            # 解析返回结果
            result_text = response.choices[0].message.content
            print(f"[+] 大模型返回结果获取成功")
            
            # [核心节点：物理剥壳机]：精准提取 JSON 实体，无论 LLM 加多少废话
            try:
                result_dict = self._clean_and_parse_json(result_text)
                
                # [核心节点]：利用 Pydantic 强校验专家画像数据，强制注入 expert_id
                # 优先使用 LLM 返回的 expert_id，否则使用传入的 expert_id
                profile_expert_id = result_dict.get('expert_id', expert_id)
                profile = DigitalTwinProfile(
                    expert_id=profile_expert_id,  # [核心节点]：强制注入 expert_id
                    expert_name=result_dict.get('expert_name', '未知专家'),
                    domain_expertise=result_dict.get('domain_expertise', ''),
                    communication_style=result_dict.get('communication_style', {}),
                    business_redlines=result_dict.get('business_redlines', []),
                    golden_few_shots=result_dict.get('golden_few_shots', []),
                    supported_intents=result_dict.get('supported_intents', ['业务咨询', '问题诊断', '闲聊兜底'])
                )
                
                print(f"[+] 成功解析 DigitalTwinProfile: {profile.expert_name}")
                print(f"[+] 专业领域: {profile.domain_expertise}")
                print(f"[+] 业务红线数量: {len(profile.business_redlines)}")
                return profile
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[致命拦截] DigitalTwinDistiller JSON 解析失败: {e}")
                print(f"[物理剥壳] 尝试备用方案，使用默认专家画像...")
                log_error("DISTILLER_JSON_FAILED", str(e), "DigitalTwinDistiller")
                print(f"[!] 错误截断内容: {result_text[:500]}")
                log_error("JSON_DECODE_ERROR", str(e), "DigitalTwinDistiller")
                raise ValueError(f"无法从返回结果中提取有效 JSON")
                
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[!] 数字孪生侧写失败: {error_type}: {error_msg}")
            
            # [核心节点]：网络错误特殊提示
            if "ConnectError" in error_type or "Connection" in error_msg:
                print(f"[!] 网络连接错误，请检查：")
                print(f"    1. BASE_URL 配置是否正确")
                print(f"    2. 网络是否需要代理设置")
                print(f"    3. 运行 python debug_api.py 进行诊断")
            
            # [核心节点]：降级返回默认专家画像（必须包含 expert_id）
            from datetime import datetime
            fallback_id = f"fallback_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            return DigitalTwinProfile(
                expert_id=fallback_id,
                expert_name="未命名专家",
                domain_expertise="待分析",
                communication_style={},
                business_redlines=[],
                golden_few_shots=[],
                supported_intents=['业务咨询', '问题诊断', '闲聊兜底']
            )


def run_map_reduce_etl(
    input_file: str = "date_0120_fixed.jsonl",
    output_dir: str = "data",
    skip_llm: bool = False,
    max_workers: int = 3,
    test_single_chunk: bool = False,
    skip_identity: bool = False,
    skip_reduce: bool = False,
    force_rebuild: bool = False
):
    """
    运行 Map-Reduce ETL 流程
    
    Args:
        input_file: 输入 JSONL 文件名
        output_dir: 输出目录
        skip_llm: 是否跳过 LLM 调用
        max_workers: 并发线程数
        force_rebuild: 是否强制重炼（需要指挥官授权）
    """
    # [核心节点]：ETL 算力锁
    if not force_rebuild and not os.getenv("FORCE_ETL_REBUILD"):
        print("[拦截] 全量语料清洗需消耗大量算力，当前处于锁定状态。如需重炼，请联系指挥官授权。")
        return
    
    print("=" * 80)
    print("Map-Reduce ETL 语料蒸馏引擎 - 启动")
    print("=" * 80)
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    print(f"[+] 输出目录已准备: {os.path.abspath(output_dir)}")
    
    # 步骤 1: 智能切块
    print(f"\n{'='*80}")
    print(f"步骤 1: 智能切块 - 语义边界切片器")
    print(f"{'='*80}")
    chunker = SemanticChunker(qa_pairs_per_chunk=10)
    chunks = chunker.load_and_chunk(input_file)
    
    if skip_llm:
        print(f"\n[!] 跳过 LLM 调用，仅完成切块")
        return
    
    # [核心节点]：在 Map 阶段前生成 expert_id（前置注入点）
    expert_manager = get_expert_manager()
    temp_expert_name = EXPERT_NAME or "未命名专家"
    current_expert_id = expert_manager.generate_expert_id(temp_expert_name)
    print(f"[+] 生成专家唯一标识（前置）: {current_expert_id}")
    print(f"[+] 此 ID 将注入到所有知识切片和专家画像")
    
    # 步骤 2: 并发 Map 阶段
    print(f"\n{'='*80}")
    print(f"步骤 2: 企业级知识提取 - Map Phase (并发处理)")
    print(f"{'='*80}")
    
    map_node = LLMMapNode()
    all_chunks = []
    
    start_time = time.time()
    
    # 测试模式：只处理第一个 Chunk
    if test_single_chunk:
        print(f"[测试模式] 仅处理第一个 Chunk 进行调试")
        chunks = chunks[:1]
        max_workers = 1
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务（注入 expert_id 到每个 chunk 处理）
        future_to_chunk = {
            executor.submit(map_node.extract_chunk, chunk, i, current_expert_id): i
            for i, chunk in enumerate(chunks)
        }
        
        # 收集结果
        for future in as_completed(future_to_chunk):
            chunk_index = future_to_chunk[future]
            try:
                knowledge_chunks = future.result()
                all_chunks.extend(knowledge_chunks)
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                print(f"[!] 切片 {chunk_index + 1} 异常: {error_type}: {error_msg}")
                
                # [核心节点]：网络错误特殊提示
                if "ConnectError" in error_type or "Connection" in error_msg:
                    print(f"[!] 网络连接错误，请检查：")
                    print(f"    1. BASE_URL 配置是否正确")
                    print(f"    2. 网络是否需要代理设置")
                    print(f"    3. 运行 python debug_api.py 进行诊断")
    
    elapsed_time = time.time() - start_time
    print(f"\n[+] Map 阶段完成，耗时 {elapsed_time:.2f} 秒")
    print(f"[+] 共提取 {len(all_chunks)} 条企业级知识切片")
    
    # [核心节点]：绝对的物理熔断锁 (The Kill Switch)
    if not all_chunks:
        print("\n[致命拦截] 知识提取阶段未能获取任何有效数据！")
        print("原因：数据源不匹配或大模型连续纠错失败。")
        print("动作：已物理切断后续 Reduce 和画像侧写流程，防止产生幻觉。")
        return None, None
    
    # [核心节点]：双重保障 - 确保所有 chunks 都有 expert_id
    injected_count = 0
    for chunk in all_chunks:
        if not hasattr(chunk, 'expert_id') or not chunk.expert_id:
            chunk.expert_id = current_expert_id
            injected_count += 1
    if injected_count > 0:
        print(f"[+] 为 {injected_count} 条知识切片注入 expert_id")
    
    # 步骤 3: Reduce 阶段
    if not skip_reduce:
        print(f"\n{'='*80}")
        print(f"步骤 3: 首席知识官审查 - Reduce Phase")
        print(f"{'='*80}")
        
        judge = LLMJudgeReduce()
        final_corpus = judge.judge_and_reduce(all_chunks, current_expert_id)
    else:
        print(f"\n[!] 跳过 Reduce 阶段，直接使用 Map 阶段输出")
        final_corpus = all_chunks
    
    # 保存结构化语料库
    corpus_path = os.path.join(output_dir, "enterprise_knowledge_base.json")
    with open(corpus_path, 'w', encoding='utf-8') as f:
        json.dump([chunk.model_dump() for chunk in final_corpus], f, ensure_ascii=False, indent=2)
    print(f"[+] 企业级知识库已保存至: {corpus_path}")
    
    expert_id = None  # 用于后续向量化入库
    if not skip_identity:
        print(f"\n{'='*80}")
        print(f"步骤 4: 数字孪生侧写师 - 提取企业专家画像")
        print(f"{'='*80}")
        print(f"[+] 正在侧写专家: {EXPERT_NAME} | 客户: {CLIENT_NAME}")
        distiller = DigitalTwinDistiller()
        # [核心节点]：将 expert_id 注入到蒸馏过程
        digital_twin = distiller.distill_digital_twin(final_corpus, current_expert_id)
        
        # [核心节点]：使用生成的 expert_id（如果 LLM 没有返回）
        expert_id = digital_twin.expert_id or current_expert_id
        digital_twin.expert_id = expert_id
        print(f"[+] 专家唯一标识确认: {expert_id}")
        
        # [核心节点]：为所有知识切片强制赋值 expert_id
        for chunk in final_corpus:
            chunk.expert_id = expert_id
        
        # 保存专家画像（兼容旧路径）
        identity_path = os.path.join(output_dir, "digital_twin_profile.json")
        with open(identity_path, 'w', encoding='utf-8') as f:
            json.dump(digital_twin.model_dump(), f, ensure_ascii=False, indent=2)
        print(f"[+] DigitalTwinProfile 已保存至: {identity_path}")
        
        # [核心节点]：使用 ExpertManager 保存专家数据
        # [核心节点]：使用与全局 enterprise_knowledge_base.json 完全相同的 final_corpus 对象
        # 严禁中间发生二次处理，确保数量 100% 对齐
        print(f"\n{'='*80}")
        print(f"步骤 4.5: 专家数据结构化存储")
        print(f"{'='*80}")
        try:
            save_success = expert_manager.save_expert(
                expert_id=expert_id,
                profile=digital_twin,
                knowledge_base=final_corpus  # [核心节点]：共享同一对象，零拷贝
            )
            if save_success:
                print(f"[+] 专家 {expert_id} 数据已结构化保存至 data/experts/")
            else:
                print(f"[!] 专家 {expert_id} 数据保存失败")
        except Exception as e:
            print(f"[!] 专家数据保存异常（非致命）: {type(e).__name__}: {e}")
            print(f"[!] 全局知识库已保存，隔离知识库写入失败，请手动检查")

    else:
        print(f"\n[!] 跳过数字孪生侧写步骤")
        digital_twin = None
    
    # [核心节点]：步骤 5 - 自动向量化入库（核心联动）
    if expert_id and final_corpus:
        print(f"\n{'='*80}")
        print(f"步骤 5: 知识向量化入库 - 向量数据库")
        print(f"{'='*80}")
        try:
            vector_engine = HybridSearchEngine()
            vector_engine.upsert_full_corpus(
                expert_id=expert_id,
                knowledge_base=final_corpus
            )
            print(f"[+] 专家 {expert_id} 知识库已自动向量化入库")
        except Exception as e:
            print(f"[!] 向量化入库失败: {e}")
            print(f"[!] 请手动运行向量入库脚本修复")
    
    # [物理切除]：步骤 5 的 SillyTavern 兼容格式导出已删除
    # B 端企业系统不需要酒馆适配器
    
    # 打印摘要
    print(f"\n{'='*80}")
    print(f"Map-Reduce ETL 流程执行完成")
    print(f"{'='*80}")
    print(f"摘要:")
    print(f"  - 处理 Chunk 数: {len(chunks)}")
    print(f"  - Map 阶段提取: {len(all_chunks)} 条企业级知识")
    print(f"  - Reduce 阶段精选: {len(final_corpus)} 条高纯度知识")
    if digital_twin:
        print(f"  - 提取专家画像: {digital_twin.expert_name} ({expert_id})")
        print(f"  - 专家数据目录: data/experts/{expert_id}/")
        print(f"  - 向量入库状态: {'完成' if expert_id else '跳过'}")
    else:
        print(f"  - 数字孪生侧写: 已跳过")
    print(f"  - 总耗时: {elapsed_time:.2f} 秒")
    print(f"{'='*80}")
    
    # [核心节点]：返回最终语料库和专家画像供调用者使用
    return final_corpus, digital_twin


if __name__ == "__main__":
    # [物理旁路 V2.0]：一键点火炼丹
    # 彻底简化 DX：拒绝反人类的一行命令，直接执行 python services/etl_pipeline.py
    print("=" * 80)
    print("🔥 正在启动本地黄金语料蒸馏流程 (ETL)...")
    print("=" * 80)
    
    # 强制设置环境变量，确保可以重炼
    os.environ["FORCE_ETL_REBUILD"] = "1"
    
    run_map_reduce_etl(
        input_file="data/staging/demo_staging.jsonl",
        output_dir="data",
        force_rebuild=True,
        skip_identity=False
    )

