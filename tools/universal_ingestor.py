"""
通用数据接入智能体 - Universal Ingestion Agent
工业级配置驱动型数据接入组件

用途：
1. 自动嗅探任何 CSV/JSONL/XLSX 文件的数据结构
2. 调用大模型进行 Schema 推断与角色对齐
3. 动态应用映射，统一转换为标准对话格式
4. 自动同步环境变量配置

[核心节点]：系统的唯一数据入口，淘汰所有硬编码解析脚本
"""

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv
import openai

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# [核心节点]：工业级容错库
try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ImportError:
    print("[错误] 未找到 tenacity 库，请先安装: pip install tenacity")
    sys.exit(1)

# 加载环境变量
load_dotenv()

# [核心节点]：全局 LLM 超时配置 - 防止网络阻塞导致假死
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

# [核心节点]：物理熔断机制 - 绝对红线
MAX_SAMPLES = 300

# [核心节点]：错误日志配置
ERROR_LOG_DIR = Path("logs")
ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
ERROR_LOG_FILE = ERROR_LOG_DIR / "ingestor_error_log.txt"

def log_ingestor_error(error_type: str, error_msg: str, context: str = ""):
    """
    [核心节点]：错误日志记录函数
    将所有 JSONDecodeError 和其他异常记录到日志文件
    """
    from datetime import datetime
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

# [核心节点]：默认输入路径（规范化目录结构）
DEFAULT_INPUT_PATH = "data/raw/source_data.csv"

# [核心节点]：标准输出路径（动态时间戳）
OUTPUT_FILE = "data/standard_ingestion.jsonl"  # 保持向后兼容


class UniversalIngestionAgent:
    """
    通用数据接入智能体
    
    [核心节点]：通过大模型推理实现零配置数据接入
    自动推断数据结构、角色映射，统一标准化输出
    """
    
    def __init__(self):
        """初始化通用接入智能体"""
        self.api_key = os.getenv("SILICONFLOW_API_KEY")
        self.base_url = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")
        self.model = os.getenv("INGESTION_MODEL", "Qwen/Qwen2.5-72B-Instruct")
        
        if not self.api_key:
            raise ValueError("致命错误：未检测到 SILICONFLOW_API_KEY")
        
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        
        # 确保输出目录存在
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
        
        print("=" * 70)
        print("🤖 通用数据接入智能体 - Universal Ingestion Agent")
        print("=" * 70)
        print(f"[配置] 模型: {self.model}")
        print(f"[配置] API: {self.base_url}")
        print(f"[配置] 熔断阈值: {MAX_SAMPLES} 条对话")
        print("=" * 70)
    
    def _read_sample_data(self, file_path: str, sample_size: int = 5) -> Tuple[str, str, List[Dict]]:
        """
        [核心节点]：探针嗅探 - 读取前N行样本数据
        
        输入：文件路径、样本数量
        输出：(文件类型, 样本文本, 完整样本数据列表)
        
        支持格式：.csv, .jsonl, .xlsx
        """
        print(f"\n[Agent] 正在嗅探数据结构: {file_path}")
        
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        ext = path.suffix.lower()
        samples = []
        
        if ext == '.csv':
            # CSV 格式嗅探
            try:
                import pandas as pd
                df = pd.read_csv(file_path, nrows=sample_size)
                samples = df.to_dict('records')
                file_type = "CSV"
            except Exception as e:
                print(f"[!] CSV 读取失败: {e}")
                raise
        
        elif ext == '.jsonl':
            # JSONL 格式嗅探
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f):
                        if i >= sample_size:
                            break
                        if line.strip():
                            samples.append(json.loads(line))
                file_type = "JSONL"
            except Exception as e:
                print(f"[!] JSONL 读取失败: {e}")
                raise
        
        elif ext in ['.xlsx', '.xls']:
            # Excel 格式嗅探
            try:
                import pandas as pd
                df = pd.read_excel(file_path, nrows=sample_size)
                samples = df.to_dict('records')
                file_type = "Excel"
            except Exception as e:
                print(f"[!] Excel 读取失败: {e}")
                raise
        
        else:
            raise ValueError(f"不支持的文件格式: {ext}，仅支持 .csv, .jsonl, .xlsx")
        
        # 转换为可读的文本样本
        sample_text = json.dumps(samples, ensure_ascii=False, indent=2)
        
        print(f"[✓] 嗅探完成: {file_type} 格式，提取 {len(samples)} 条样本")
        return file_type, sample_text, samples
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def _infer_schema_with_llm(self, sample_text: str, file_type: str) -> Dict[str, Any]:
        """
        [核心节点]：大模型 Schema 嗅探与对齐
        
        输入：样本文本、文件类型
        输出：Schema 映射配置字典
        
        原理：调用大模型分析数据结构，推断角色映射关系
        """
        print(f"\n[Agent] 正在调用大模型进行 Schema 推断...")
        
        system_prompt = """你是一个数据 schema 分析专家。你的任务是分析给定的数据样本，识别出代表"用户提问"、"专家回答"和"时间戳"的列名或键名。

请仔细分析数据结构，输出严格的 JSON 格式映射关系：

{
  "client_col": "代表用户提问的列名/键名（可以是一个或多个组合）",
  "expert_col": "代表专家回答的列名/键名",
  "timestamp_col": "代表时间戳的列名/键名（如：timestamp, time, date, created_at等），如果没有则设为 null",
  "inferred_client_name": "推断出的客户称呼（如：买家、患者、用户、客户）",
  "inferred_expert_name": "推断出的专家称呼（如：金牌客服、主治医师、技术支持、专家）",
  "expert_id_short": "将专家称呼转换为纯英文/拼音缩写（如：erke_yisheng、jinpaifuwu、jishouzhichi）",
  "reasoning": "简要说明推断理由"
}

【强制要求】：
1. 必须基于数据内容，给出一个简洁的中文专家角色名（如：儿科医生、架构师、客服）
2. 必须生成 expert_id_short 字段，将专家角色名转换为纯英文/拼音缩写
3. expert_id_short 只能包含字母和下划线，不能包含中文字符
4. 必须检查是否存在时间戳列（timestamp, time, date, created_at等），如果有必须指定
5. 如果是问答对格式（question/answer），client_col 对应 question，expert_col 对应 answer
6. 如果是对话格式（speaker/content），client_col 可能是 "speaker"，需要结合内容判断
7. 如果是医疗数据，client_name 可能是"患者"，expert_name 可能是"医生"
8. 如果是客服数据，client_name 可能是"买家"，expert_name 可能是"客服"
9. 如果有多列组合（如 title + input），请用逗号分隔列名
10. 如果没有时间戳列，timestamp_col 必须设为 null

只输出 JSON，不要任何解释性文字。"""

        user_prompt = f"""数据文件类型: {file_type}

数据样本（前5行）:
```json
{sample_text}
```

请分析这个数据的结构，输出 JSON 映射关系。"""

        try:
            # [核心节点]：使用全局超时配置，防止网络阻塞
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"},
                timeout=LLM_TIMEOUT  # [核心节点]：超时控制防止假死
            )
            
            result_text = response.choices[0].message.content
            
            # 解析 JSON 结果
            try:
                schema_mapping = json.loads(result_text)
            except json.JSONDecodeError as e:
                # [核心节点]：记录 JSON 解析错误并尝试提取
                log_ingestor_error("JSONDecodeError", str(e), f"Raw response: {result_text[:200]}")
                # 尝试提取 JSON 部分
                json_start = result_text.find('{')
                json_end = result_text.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    try:
                        schema_mapping = json.loads(result_text[json_start:json_end])
                    except json.JSONDecodeError as e2:
                        log_ingestor_error("JSONDecodeError", str(e2), "Fallback extraction failed")
                        raise ValueError(f"无法解析大模型返回的 JSON: {e2}")
                else:
                    raise ValueError("大模型返回不是有效 JSON")
            
            # 验证必需字段
            required_fields = ['client_col', 'expert_col', 'inferred_client_name', 'inferred_expert_name', 'expert_id_short', 'timestamp_col']
            for field in required_fields:
                if field not in schema_mapping:
                    schema_mapping[field] = "unknown" if field != 'timestamp_col' else None
            
            # [核心节点]：确保 expert_id_short 存在且有效
            if schema_mapping.get('expert_id_short') == 'unknown':
                # 基于专家名生成默认 expert_id_short
                expert_name = schema_mapping.get('inferred_expert_name', 'unknown')
                import re
                expert_id_short = re.sub(r'[^a-zA-Z]', '', expert_name).lower()
                if not expert_id_short:
                    expert_id_short = 'expert'
                schema_mapping['expert_id_short'] = expert_id_short
                print(f"[!] 生成默认 expert_id_short: {expert_id_short}")
            
            # [核心节点]：检查时间戳列
            timestamp_col = schema_mapping.get('timestamp_col')
            if timestamp_col is None or timestamp_col == 'unknown':
                print(f"[信息]：源数据无时间戳列，将输出无时间戳的纯净数据")
                schema_mapping['timestamp_col'] = None
            else:
                print(f"[✓] 发现时间戳列: {timestamp_col}")
            
            print(f"[✓] Schema 推断完成")
            print(f"    用户列: {schema_mapping['client_col']}")
            print(f"    专家列: {schema_mapping['expert_col']}")
            print(f"    时间戳列: {schema_mapping['timestamp_col'] or '无'}")
            print(f"    推断角色: {schema_mapping['inferred_client_name']} → {schema_mapping['inferred_expert_name']}")
            
            return schema_mapping
            
        except Exception as e:
            error_type = type(e).__name__
            log_ingestor_error(error_type, str(e), "_infer_schema_with_llm")
            print(f"[!] LLM Schema 推断失败: {error_type}: {e}")
            raise
    
    def _apply_mapping_and_transform(
        self, 
        file_path: str, 
        schema_mapping: Dict[str, Any],
        file_type: str
    ) -> int:
        """
        [核心节点]：动态应用映射与熔断
        
        输入：文件路径、Schema映射、文件类型
        输出：成功提取的对话数量
        
        原理：根据大模型推断的映射关系，遍历整个文件，提取并标准化为统一格式
        [绝对红线]：MAX_SAMPLES = 300 物理熔断
        """
        print(f"\n[Agent] 开始全量数据转换...")
        print(f"[配置] 物理熔断阈值: {MAX_SAMPLES} 条")
        
        client_col = schema_mapping['client_col']
        expert_col = schema_mapping['expert_col']
        timestamp_col = schema_mapping.get('timestamp_col')
        client_name = schema_mapping['inferred_client_name']
        expert_name = schema_mapping['inferred_expert_name']
        
        # 处理组合列名（逗号分隔）
        client_cols = [c.strip() for c in client_col.split(',') if c.strip() != 'unknown']
        
        processed_count = 0
        output_records = []
        
        # 根据文件类型读取完整数据
        path = Path(file_path)
        ext = path.suffix.lower()
        
        if ext == '.csv':
            import pandas as pd
            df = pd.read_csv(file_path)
            records = df.to_dict('records')
        elif ext == '.jsonl':
            records = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
        elif ext in ['.xlsx', '.xls']:
            import pandas as pd
            df = pd.read_excel(file_path)
            records = df.to_dict('records')
        else:
            records = []
        
        print(f"[Agent] 读取到 {len(records)} 条原始记录")
        
        # 遍历转换
        for idx, record in enumerate(records):
            # [绝对红线]：物理熔断检查
            if processed_count >= MAX_SAMPLES:
                print(f"\n[!] 熔断触发！已达到 {MAX_SAMPLES} 条上限，终止处理")
                break
            
            try:
                # 提取客户内容（支持组合列）
                client_content_parts = []
                for col in client_cols:
                    if col in record and record[col]:
                        client_content_parts.append(str(record[col]))
                
                if not client_content_parts:
                    continue
                    
                client_content = " ".join(client_content_parts)
                
                # 提取专家内容
                expert_content = str(record.get(expert_col, ""))
                
                if not client_content.strip() or not expert_content.strip():
                    continue
                
                # [核心节点]：物理时间轴映射 - 使用真实时间戳
                if timestamp_col and timestamp_col in record and record[timestamp_col]:
                    # 使用原始时间戳
                    raw_timestamp = str(record[timestamp_col])
                    try:
                        # 尝试解析时间戳
                        if isinstance(record[timestamp_col], (int, float)):
                            # Unix 时间戳
                            timestamp = datetime.fromtimestamp(record[timestamp_col]).isoformat()
                        else:
                            # 字符串时间戳，尝试多种格式
                            import dateutil.parser
                            parsed_time = dateutil.parser.parse(raw_timestamp)
                            timestamp = parsed_time.isoformat()
                    except Exception as e:
                        print(f"[!] 时间戳解析失败: {raw_timestamp}, 跳过时间戳")
                        timestamp = None
                else:
                    # [工程红线]：无时间列时不生成虚假时间戳
                    timestamp = None
                    if processed_count == 0:
                        print(f"[信息]：源数据无时间戳列，将输出无时间戳的纯净数据")
                
                # 构建标准格式对话（一问一答算一条 QA Pair）
                # 拆分为两条记录：客户提问 + 专家回答
                
                # 客户提问
                client_record = {
                    "speaker": client_name,
                    "content": client_content
                }
                if timestamp is not None:
                    client_record["timestamp"] = timestamp
                output_records.append(client_record)
                
                # 专家回答
                expert_record = {
                    "speaker": expert_name,
                    "content": expert_content
                }
                if timestamp is not None:
                    # 如果有真实时间戳，专家回答时间+1秒
                    try:
                        from datetime import datetime, timedelta
                        base_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        expert_timestamp = (base_time + timedelta(seconds=1)).isoformat()
                        expert_record["timestamp"] = expert_timestamp
                    except:
                        expert_record["timestamp"] = timestamp  # 如果解析失败，使用相同时间戳
                
                output_records.append(expert_record)
                
                processed_count += 1
                
                # 每50条打印进度
                if processed_count % 50 == 0:
                    print(f"    进度: {processed_count}/{MAX_SAMPLES}")
                
            except Exception as e:
                print(f"[!] 跳过第 {idx+1} 条记录（解析失败）: {e}")
                continue
        
        # 写入标准输出文件
        print(f"\n[Agent] 正在写入标准输出: {OUTPUT_FILE}")
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            for record in output_records:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        print(f"[✓] 转换完成: {len(output_records)} 条消息（{processed_count} 对对话）")
        
        return processed_count, client_name, expert_name
    
    def _generate_timestamped_filename(self, expert_id_short: str) -> str:
        """
        [核心节点]：生成带时间戳的暂存文件名
        格式：staging_{expert_id_short}_{YYYYMMDD_HHMMSS}.jsonl
        """
        from datetime import datetime
        
        # 使用 LLM 返回的 expert_id_short
        if not expert_id_short or expert_id_short == 'unknown':
            expert_id_short = "expert"
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"staging_{expert_id_short}_{timestamp}.jsonl"
        return filename
    
    def _cleanup_old_staging_files(self, staging_dir: Path, current_filename: str):
        """
        [核心节点]：清理旧的暂存文件，只保留最新的一份
        修复：先确保新文件已存在，再删除旧文件，避免自残
        """
        try:
            import glob
            
            # [关键修复]：先检查当前文件是否存在
            current_file_path = staging_dir / current_filename
            if not current_file_path.exists():
                print(f"[!] 当前文件不存在，跳过清理: {current_filename}")
                return
            
            # 查找所有暂存文件
            staging_files = glob.glob(str(staging_dir / "staging_*.jsonl"))
            
            # 删除除当前文件外的所有文件
            for file_path in staging_files:
                file_name = Path(file_path).name
                if file_name != current_filename:
                    try:
                        Path(file_path).unlink()
                        print(f"[清理] 已删除旧暂存文件: {file_name}")
                    except Exception as e:
                        print(f"[!] 删除文件失败: {file_name}, 错误: {e}")
            
            # 检查并删除 standard_ingestion.jsonl（冗余文件）
            standard_file = staging_dir.parent / "standard_ingestion.jsonl"
            if standard_file.exists():
                try:
                    standard_file.unlink()
                    print(f"[清理] 已删除冗余文件: standard_ingestion.jsonl")
                except Exception as e:
                    print(f"[!] 删除冗余文件失败: {e}")
                    
        except Exception as e:
            print(f"[!] 清理暂存文件失败: {e}")
    
    def _update_latest_staging_env(self, filepath: str):
        """
        [核心节点]：将最新的暂存文件路径写入 .env
        """
        try:
            env_file = Path(".env")
            env_content = ""
            
            # 读取现有 .env 内容
            if env_file.exists():
                with open(env_file, "r", encoding="utf-8") as f:
                    env_content = f.read()
            
            # 更新或添加 LATEST_STAGING_FILE
            lines = env_content.split('\n')
            updated_lines = []
            staging_updated = False
            
            for line in lines:
                if line.startswith('LATEST_STAGING_FILE='):
                    updated_lines.append(f'LATEST_STAGING_FILE={filepath}')
                    staging_updated = True
                else:
                    updated_lines.append(line)
            
            if not staging_updated:
                updated_lines.append(f'LATEST_STAGING_FILE={filepath}')
            
            # 写回 .env 文件
            with open(env_file, "w", encoding="utf-8") as f:
                f.write('\n'.join(updated_lines))
            
            print(f"[✓] 已更新 .env 中的 LATEST_STAGING_FILE: {filepath}")
            
        except Exception as e:
            print(f"[!] 更新 LATEST_STAGING_FILE 失败: {e}")
    
    def _update_env_variables(self, client_name: str, expert_name: str):
        """
        更新环境变量文件
        """
        try:
            env_file = Path(".env")
            env_content = ""
            
            # 读取现有 .env 内容
            if env_file.exists():
                with open(env_file, "r", encoding="utf-8") as f:
                    env_content = f.read()
            
            # 更新或添加变量
            lines = env_content.split('\n')
            updated_lines = []
            client_updated = False
            expert_updated = False
            
            for line in lines:
                if line.startswith('CLIENT_NAME='):
                    updated_lines.append(f'CLIENT_NAME={client_name}')
                    client_updated = True
                elif line.startswith('EXPERT_NAME='):
                    updated_lines.append(f'EXPERT_NAME={expert_name}')
                    expert_updated = True
                else:
                    updated_lines.append(line)
            
            if not client_updated:
                updated_lines.append(f'CLIENT_NAME={client_name}')
            if not expert_updated:
                updated_lines.append(f'EXPERT_NAME={expert_name}')
            
            # 写回 .env 文件
            with open(env_file, "w", encoding="utf-8") as f:
                f.write('\n'.join(updated_lines))
            
            print(f"[✓] 已更新环境变量: CLIENT_NAME={client_name}, EXPERT_NAME={expert_name}")
            
        except Exception as e:
            print(f"[!] 更新环境变量失败: {e}")
    
    def ingest(self, file_path: str) -> Dict[str, Any]:
        """
        主入口：执行完整的数据接入流程
        
        输入：任意 CSV/JSONL/XLSX 文件路径
        输出：处理结果摘要
        
        流程：嗅探样本 → LLM推断Schema → 全量转换 → 同步环境变量
        """
        print(f"\n{'='*70}")
        print(f"开始数据接入流程: {file_path}")
        print(f"{'='*70}")
        
        try:
            # 步骤 1：探针嗅探
            file_type, sample_text, _ = self._read_sample_data(file_path)
            
            # 步骤 2：LLM Schema 推断
            schema_mapping = self._infer_schema_with_llm(sample_text, file_type)
            
            # 步骤 3：动态映射与熔断
            processed_count, client_name, expert_name = self._apply_mapping_and_transform(
                file_path, schema_mapping, file_type
            )
            
            # 步骤 4：生成带时间戳的暂存文件（使用 expert_id_short）
            expert_id_short = schema_mapping.get('expert_id_short', 'unknown')
            staging_filename = self._generate_timestamped_filename(expert_id_short)
            staging_dir = Path("data/staging")
            staging_dir.mkdir(parents=True, exist_ok=True)
            staging_path = staging_dir / staging_filename
            
            # 步骤 5：写入暂存文件（确保物理写入）
            print(f"[Agent] 正在写入暂存文件: {staging_path}")
            with open(staging_path, 'w', encoding='utf-8') as f:
                # 读取标准输出文件内容并写入暂存文件
                standard_file = Path(OUTPUT_FILE)
                if standard_file.exists():
                    with open(standard_file, 'r', encoding='utf-8') as src:
                        for line in src:
                            f.write(line)
                    f.flush()  # 强制刷新缓冲区
                    os.fsync(f.fileno())  # 强制同步到磁盘
                else:
                    raise FileNotFoundError(f"标准输出文件不存在: {OUTPUT_FILE}")
            
            # 步骤 6：清理旧暂存文件（在写入完成后执行）
            self._cleanup_old_staging_files(staging_dir, staging_filename)
            
            # 步骤 7：环境变量同步（包括 LATEST_STAGING_FILE）
            self._update_env_variables(client_name, expert_name)
            self._update_latest_staging_env(str(staging_path.absolute()))
            
            # 步骤 8：终端物理确认
            latest_file_path = str(staging_path.absolute())
            if os.path.exists(latest_file_path):
                file_size = os.path.getsize(latest_file_path)
                print(f"[验证] 物理文件真实存在，大小: {file_size} 字节")
            else:
                print(f"[严重警告] 文件写入后丢失！请检查逻辑。")
            
            # 汇总报告
            expert_id_short = schema_mapping.get('expert_id_short', 'unknown')
            print(f"\n{'='*70}")
            print("🎉 数据接入流程完成！")
            print(f"{'='*70}")
            print(f"输入文件: {file_path}")
            print(f"输出文件: {OUTPUT_FILE}")
            print(f"暂存文件: {staging_path}")
            print(f"提取对话: {processed_count} 对（熔断阈值: {MAX_SAMPLES}）")
            print(f"角色映射: {client_name} → {expert_name} (ID: {expert_id_short})")
            print(f"环境变量: 已自动同步到 .env")
            print(f"{'='*70}")
            
            return {
                "success": True,
                "input_file": file_path,
                "output_file": OUTPUT_FILE,
                "staging_file": str(staging_path),
                "processed_count": processed_count,
                "client_name": client_name,
                "expert_name": expert_name,
                "expert_id_short": expert_id_short,
                "schema_mapping": schema_mapping
            }
            
        except Exception as e:
            print(f"\n[✗] 数据接入失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="通用数据接入智能体 - 自动解析 CSV/JSONL/XLSX 文件"
    )
    parser.add_argument(
        "file",
        help="输入文件路径 (.csv, .jsonl, .xlsx)"
    )
    
    args = parser.parse_args()
    
    # 创建智能体并执行接入
    agent = UniversalIngestionAgent()
    result = agent.ingest(args.file)
    
    if result["success"]:
        print("\n✅ 准备就绪，可以运行: python services/etl_pipeline.py")
    else:
        print("\n❌ 接入失败，请检查错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
