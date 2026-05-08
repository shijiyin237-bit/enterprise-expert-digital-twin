"""
企业级本地数据解析探针 - 高泛化数据归一化网关
遵循"数据接入与处理解耦"原则，专门处理企业异构本地脏数据
支持两种主流格式：
  A类：扁平格式 {"speaker": "...", "content": "..."}
  B类：嵌套格式 [{"role": "user", "content": "..."}, ...]

用途：读取本地 CSV/Excel 文件，归一化为标准 JSONL 格式供 ETL 引擎消费
实现"一次清洗，全系统通用"
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# [核心节点]：尝试导入 pandas，如未安装则给出友好提示
try:
    import pandas as pd
except ImportError:
    print("[错误] 未找到 pandas 库，请先安装: pip install pandas openpyxl")
    print("[提示] openpyxl 用于读取 .xlsx 文件")
    sys.exit(1)


# [核心节点]：Token 熔断锁（核心红线）
# 一旦成功解析提取出 300 对有效的一问一答，立刻终止脚本
# 绝对禁止全量转换以防止后续 ETL 步骤 Token 爆炸！
MAX_SAMPLES = 300

# [核心节点]：输出文件路径，统一暂存区命名（覆盖写入机制）
OUTPUT_FILE = "data/staging_corpus.jsonl"

# [核心节点]：输入文件路径占位符（可通过命令行参数覆盖）
DEFAULT_INPUT_PATH = "source_data.csv"


def detect_format_type(cell_str: str) -> str:
    """
    格式检测器：识别数据是 A类 还是 B类 格式
    
    输入：单元格字符串
    输出："A" (扁平格式) 或 "B" (嵌套数组格式) 或 "unknown"
    
    [核心节点]：多格式检测是数据归一化的第一步
    """
    cell_str = cell_str.strip()
    
    # B类格式特征：以 [ 开头，包含多个 {"role": ..., "content": ...} 对象
    if cell_str.startswith("["):
        return "B"
    
    # A类格式特征：以 { 开头，包含 speaker 和 content 字段
    if cell_str.startswith("{"):
        try:
            parsed = json.loads(cell_str)
            if "speaker" in parsed and "content" in parsed:
                return "A"
        except:
            pass
    
    return "unknown"


def clean_csv_escaped_json(cell_str: str) -> str:
    """
    清洗 CSV 转义的 JSON 字符串
    
    输入：CSV 中的转义字符串（如 ""{...}"")
    输出：清洗后的标准 JSON 字符串
    
    [核心节点]：处理企业 CSV 中的双引号转义和首尾多余引号
    """
    # 步骤1：去除首尾多余的引号
    cell_str = cell_str.strip()
    if cell_str.startswith('"') and cell_str.endswith('"'):
        cell_str = cell_str[1:-1]
    
    # 步骤2：将 "" 替换为 "（CSV 双引号转义标准化）
    cell_str = cell_str.replace('""', '"')
    
    return cell_str


def parse_format_a(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    解析 A类格式：扁平格式 {"speaker": "...", "content": "..."}
    
    输入：解析后的字典
    输出：标准化记录，或 None（如果无效）
    
    [核心节点]：直接提取，无需角色映射
    """
    speaker = data.get("speaker", "").strip()
    content = data.get("content", "").strip()
    
    if not speaker or not content:
        return None
    
    return {
        "speaker": speaker,
        "content": content
    }


def parse_format_b(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    解析 B类格式：嵌套数组格式 [{"role": "user", ...}, ...]
    
    输入：解析后的消息数组
    输出：标准化记录列表
    
    [核心节点]：逻辑提纯 - 跳过 system，映射 role 到 speaker
    """
    records = []
    
    for msg in data:
        if not isinstance(msg, dict):
            continue
        
        role = msg.get("role", "").strip().lower()
        content = msg.get("content", "").strip()
        
        # [核心节点]：跳过 system 消息
        if role == "system" or not content:
            continue
        
        # [核心节点]：核心映射 - role 转 speaker
        speaker = None
        if role == "user":
            speaker = "买家"
        elif role == "assistant":
            speaker = "金牌客服"
        
        if not speaker:
            continue
        
        records.append({
            "speaker": speaker,
            "content": content
        })
    
    return records


def extract_records_from_cell(cell_value: Any) -> List[Dict[str, Any]]:
    """
    数据归一化网关：从单元格提取并归一化为标准记录列表
    
    输入：可能包含 JSON 的单元格值
    输出：标准化记录列表（可能包含多条）
    
    [核心节点]：统一出口，一次清洗，全系统通用
    """
    if pd.isna(cell_value) or not isinstance(cell_value, str):
        return []
    
    cell_str = cell_value.strip()
    if not cell_str:
        return []
    
    records = []
    
    try:
        # [核心节点]：格式检测
        format_type = detect_format_type(cell_str)
        
        if format_type == "B":
            # B类格式：需要清洗 CSV 转义
            cleaned_str = clean_csv_escaped_json(cell_str)
            data = json.loads(cleaned_str)
            
            if isinstance(data, list):
                records = parse_format_b(data)
        
        elif format_type == "A":
            # A类格式：直接解析
            data = json.loads(cell_str)
            
            if isinstance(data, dict):
                record = parse_format_a(data)
                if record:
                    records = [record]
        
        else:
            # 未知格式，尝试模糊匹配
            # 尝试提取任何看起来像 JSON 的内容
            try:
                cleaned = clean_csv_escaped_json(cell_str)
                data = json.loads(cleaned)
                
                if isinstance(data, list):
                    records = parse_format_b(data)
                elif isinstance(data, dict):
                    if "speaker" in data:
                        record = parse_format_a(data)
                        if record:
                            records = [record]
                    elif "role" in data:
                        # 单条 B类格式
                        speaker = None
                        role = data.get("role", "").strip().lower()
                        if role == "user":
                            speaker = "买家"
                        elif role == "assistant":
                            speaker = "金牌客服"
                        
                        if speaker and data.get("content"):
                            records = [{
                                "speaker": speaker,
                                "content": data["content"].strip()
                            }]
            except:
                pass
    
    except Exception as e:
        # [核心节点]：防爆处理，任何解析失败都返回空列表
        pass
    
    return records


def parse_dataframe_to_conversations(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    将 DataFrame 解析为标准对话记录
    
    输入：包含脏数据的 pandas DataFrame
    输出：标准格式的对话记录列表
    
    [核心节点]：数据归一化网关的主入口，支持多格式混洗
    """
    records = []
    base_time = datetime.now()
    processed_rows = 0
    
    # [核心节点]：遍历 DataFrame 的每个单元格
    for col_idx, column in enumerate(df.columns):
        for row_idx, cell_value in enumerate(df[column]):
            processed_rows += 1
            
            # Token 熔断检查：300 对问答 = 600 条消息
            if len(records) >= MAX_SAMPLES * 2:
                print(f"[+] 已达到 Token 熔断阈值 {MAX_SAMPLES} 对对话，停止解析")
                return records
            
            try:
                # [核心节点]：数据归一化网关提取记录
                cell_records = extract_records_from_cell(cell_value)
                
                for record in cell_records:
                    # 生成递增时间戳
                    timestamp = base_time.replace(
                        hour=(processed_rows // 3600) % 24,
                        minute=(processed_rows // 60) % 60,
                        second=processed_rows % 60
                    ).strftime("%Y-%m-%dT%H:%M:%S")
                    
                    # 组装最终标准格式
                    final_record = {
                        "timestamp": timestamp,
                        "speaker": record["speaker"],
                        "content": record["content"]
                    }
                    records.append(final_record)
                    
            except Exception as e:
                # [核心节点]：防爆处理，打印警告但继续
                print(f"[!] 跳过坏数据行 (row={row_idx}, col={col_idx}): {str(e)[:50]}")
                continue
    
    return records


def read_local_file(file_path: str) -> Optional[pd.DataFrame]:
    """
    读取本地 CSV 或 Excel 文件
    
    输入：文件路径
    输出：pandas DataFrame，或 None（如果读取失败）
    
    [核心节点]：支持 .csv 和 .xlsx 格式，自动识别文件类型
    """
    path = Path(file_path)
    
    if not path.exists():
        print(f"[错误] 文件不存在: {file_path}")
        return None
    
    try:
        suffix = path.suffix.lower()
        
        if suffix == '.csv':
            # [核心节点]：读取 CSV，容错处理乱码
            try:
                return pd.read_csv(file_path, encoding='utf-8')
            except UnicodeDecodeError:
                # 尝试 GBK 编码
                return pd.read_csv(file_path, encoding='gbk')
        
        elif suffix in ['.xlsx', '.xls']:
            # [核心节点]：读取 Excel
            return pd.read_excel(file_path)
        
        else:
            print(f"[错误] 不支持的文件格式: {suffix}")
            return None
            
    except Exception as e:
        print(f"[错误] 读取文件失败: {e}")
        return None


def save_to_jsonl(records: List[Dict[str, Any]], output_path: str = OUTPUT_FILE):
    """
    将记录保存为 JSONL 格式
    
    [核心节点]：标准 JSON Lines 格式，每行一个 JSON 对象，行尾无逗号
    [核心节点]：物理覆写机制 - 确保不会残留上一次旧数据
    """
    try:
        # [核心节点]：物理删除旧文件（确保覆写，绝不残留旧数据）
        output_file = Path(output_path)
        if output_file.exists():
            output_file.unlink()
            print(f"[清理] 已删除旧暂存文件: {output_path}")
        
        # 确保输出目录存在
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # [核心节点]：覆盖写入模式（w），绝不追加
        with open(output_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"[错误] 保存文件失败: {e}")
        return False


def main():
    """
    主函数：企业级本地数据解析流程
    
    [核心节点]：Token 成本控制优先，严格限制 MAX_SAMPLES
    """
    print("=" * 80)
    print("企业级本地数据解析探针 - 启动")
    print("=" * 80)
    
    # 获取输入文件路径
    input_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT_PATH
    
    print(f"[+] 输入文件: {input_path}")
    print(f"[+] 输出文件: {OUTPUT_FILE}")
    print(f"[+] Token 熔断阈值: {MAX_SAMPLES} 对对话")
    print()
    
    # [核心节点]：读取本地文件
    print("[-] 正在读取本地数据文件...")
    df = read_local_file(input_path)
    if df is None:
        print("[错误] 无法读取数据文件，退出")
        sys.exit(1)
    
    print(f"[+] 成功读取数据: {len(df)} 行 x {len(df.columns)} 列")
    print()
    
    # [核心节点]：解析数据
    print("[-] 正在解析脏数据并提取有效对话...")
    records = parse_dataframe_to_conversations(df)
    
    if not records:
        print("[警告] 未提取到任何有效对话记录")
        sys.exit(0)
    
    # 统计问答对数（每2条记录为1对问答）
    qa_pairs = len(records) // 2
    print(f"[+] 成功提取: {len(records)} 条消息（约 {qa_pairs} 对问答）")
    print()
    
    # [核心节点]：保存为 JSONL
    print("[-] 正在保存为标准 JSONL 格式...")
    if save_to_jsonl(records):
        print(f"[+] 数据已保存至: {OUTPUT_FILE}")
    else:
        print("[错误] 保存失败")
        sys.exit(1)
    
    print()
    print("=" * 80)
    print("本地数据解析完成")
    print("=" * 80)
    print(f"[+] 解析统计:")
    print(f"    - 总消息数: {len(records)}")
    print(f"    - 问答对数: {qa_pairs}")
    print(f"    - 熔断状态: {'已触发' if qa_pairs >= MAX_SAMPLES else '未触发'}")
    print()
    print("[提示] 下一步: 运行 python services/etl_pipeline.py 进行 ETL 处理")


if __name__ == "__main__":
    main()
