"""
ShareGPT → JSONL 暴力拆解转换器
[核心节点]：物理旁路 - 废除 LLM Schema 猜测的脆弱逻辑

用途：
1. 读取 CSV 文件中嵌套 ShareGPT 格式的 conversations 列
2. 用 json.loads() 暴力拆解嵌套数组
3. 将 from: user 映射为 "speaker": "客户"
4. 将 from: assistant 映射为 "speaker": "专家"
5. 强制输出绝对干净的 data/staging/demo_staging.jsonl

数据契约：{"speaker": "...", "content": "..."}

[绝对红线]：不依赖任何 LLM，纯物理拆解
"""

import json
import os
import sys
import csv
from pathlib import Path
from typing import List, Dict, Any


# [核心节点]：硬编码角色映射 - 废除 LLM 猜测
ROLE_MAP = {
    "user": "客户",
    "assistant": "专家"
}

# [核心节点]：输出路径
OUTPUT_FILE = "data/staging/demo_staging.jsonl"


def parse_sharegpt_cell(cell_value: str) -> List[Dict[str, str]]:
    """
    [核心节点]：暴力拆解 ShareGPT 单元格
    
    输入：单元格字符串（可能包含 JSON 数组）
    输出：拆解后的 {"speaker": "...", "content": "..."} 列表
    
    原理：
    1. 尝试 json.loads() 直接解析
    2. 如果失败，尝试修复常见格式问题（如单引号、多余转义）
    3. 如果仍然失败，使用正则表达式暴力提取
    """
    if not cell_value or not cell_value.strip():
        return []
    
    # 步骤 1：尝试直接 json.loads()
    try:
        messages = json.loads(cell_value)
        if isinstance(messages, list):
            return _convert_messages(messages)
    except json.JSONDecodeError:
        pass
    
    # 步骤 2：尝试修复转义问题（CSV 读取时可能有多余转义）
    try:
        # 去除首尾可能的多余引号
        cleaned = cell_value.strip()
        if cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = cleaned[1:-1]
        # 修复双引号转义
        cleaned = cleaned.replace('\\"', '"').replace('""', '"')
        messages = json.loads(cleaned)
        if isinstance(messages, list):
            return _convert_messages(messages)
    except json.JSONDecodeError:
        pass
    
    # 步骤 3：正则表达式暴力提取
    return _regex_extract(cell_value)


def _convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    将 ShareGPT 消息列表转换为标准格式
    
    输入：[{"from": "user", "value": "..."}, {"from": "assistant", "value": "..."}]
    输出：[{"speaker": "客户", "content": "..."}, {"speaker": "专家", "content": "..."}]
    """
    result = []
    for msg in messages:
        from_role = msg.get("from", "").lower()
        content = msg.get("value", "") or msg.get("content", "")
        
        # 映射角色
        speaker = ROLE_MAP.get(from_role, from_role)
        
        if content and content.strip():
            result.append({
                "speaker": speaker,
                "content": content.strip()
            })
    
    return result


def _regex_extract(text: str) -> List[Dict[str, str]]:
    """
    [核心节点]：正则表达式暴力提取
    
    当 json.loads() 完全失败时的最后手段
    使用正则匹配 "from": "user"/"assistant" 和 "value": "..." 模式
    """
    import re
    
    result = []
    
    # 匹配 from 和 value 对
    # 模式：{"from": "user", "value": "..."} 或 {"from": "assistant", "value": "..."}
    pattern = r'\{\s*"from"\s*:\s*"([^"]+)"\s*,\s*"value"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
    
    matches = re.findall(pattern, text)
    
    for from_role, content in matches:
        speaker = ROLE_MAP.get(from_role.lower(), from_role)
        if content and content.strip():
            result.append({
                "speaker": speaker,
                "content": content.strip()
            })
    
    return result


def convert_csv_to_jsonl(csv_path: str, output_path: str = None) -> int:
    """
    [核心节点]：主转换函数 - CSV → JSONL
    
    输入：CSV 文件路径
    输出：写入 JSONL 文件，返回写入的记录数
    
    流程：
    1. 读取 CSV 文件
    2. 查找 conversations 列
    3. 对每一行，暴力拆解 conversations 单元格
    4. 写入标准 JSONL 格式
    """
    if output_path is None:
        output_path = OUTPUT_FILE
    
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"[!] 文件不存在: {csv_path}")
        return 0
    
    # 确保输出目录存在
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'='*70}")
    print("🔧 ShareGPT → JSONL 暴力拆解转换器")
    print(f"{'='*70}")
    print(f"[输入] {csv_path}")
    print(f"[输出] {output_path}")
    print(f"{'='*70}")
    
    total_records = 0
    total_rows = 0
    
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig 自动去除 BOM
            reader = csv.DictReader(f)
            
            # 查找 conversations 列（兼容 BOM 前缀）
            fieldnames = [name.strip().replace('\ufeff', '') for name in (reader.fieldnames or [])]
            reader.fieldnames = fieldnames
            
            if 'conversations' not in fieldnames:
                print(f"[!] 未找到 'conversations' 列")
                print(f"[!] 可用列: {fieldnames}")
                return 0

            
            with open(output_path, 'w', encoding='utf-8') as out_f:
                for row_idx, row in enumerate(reader, 1):
                    cell_value = row.get('conversations', '')
                    
                    if not cell_value or not cell_value.strip():
                        continue
                    
                    # 暴力拆解
                    messages = parse_sharegpt_cell(cell_value)
                    
                    if not messages:
                        continue
                    
                    # 写入标准格式
                    for msg in messages:
                        out_f.write(json.dumps(msg, ensure_ascii=False) + '\n')
                        total_records += 1
                    
                    total_rows += 1
                    
                    # 进度打印
                    if total_rows % 20 == 0:
                        print(f"    进度: 已处理 {total_rows} 行对话，拆解 {total_records} 条消息")
        
        print(f"\n[✓] 转换完成！")
        print(f"    处理对话行: {total_rows}")
        print(f"    拆解消息数: {total_records}")
        print(f"    输出文件: {output_path}")
        
        # 验证输出文件
        if total_records > 0:
            file_size = Path(output_path).stat().st_size
            print(f"    文件大小: {file_size} 字节")
            
            # 打印前 4 条记录作为验证
            print(f"\n[验证] 输出数据预览（前 4 条）:")
            with open(output_path, 'r', encoding='utf-8') as vf:
                for i, line in enumerate(vf):
                    if i >= 4:
                        break
                    record = json.loads(line)
                    print(f"    [{i+1}] speaker={record['speaker']}, content={record['content'][:50]}...")
        
        return total_records
        
    except Exception as e:
        print(f"[!] 转换失败: {type(e).__name__}: {e}")
        return 0


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="ShareGPT → JSONL 暴力拆解转换器"
    )
    parser.add_argument(
        "input",
        nargs='?',
        default="data/raw/source_data.csv",
        help="输入 CSV 文件路径（默认: data/raw/source_data.csv）"
    )
    parser.add_argument(
        "-o", "--output",
        default=OUTPUT_FILE,
        help=f"输出 JSONL 文件路径（默认: {OUTPUT_FILE}）"
    )
    
    args = parser.parse_args()
    
    count = convert_csv_to_jsonl(args.input, args.output)
    
    if count > 0:
        print(f"\n✅ 转换成功！共拆解 {count} 条消息")
        print(f"   数据已就绪，可以运行: python services/etl_pipeline.py")
    else:
        print(f"\n❌ 转换失败，未生成任何有效数据")
        sys.exit(1)


if __name__ == "__main__":
    main()
