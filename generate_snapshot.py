#!/usr/bin/env python3
"""
企业级项目快照生成器 V2.0 - 动态泛化嗅探版
"""

import os
from pathlib import Path
from datetime import datetime


def should_ignore(path: Path) -> bool:
    """物理级屏蔽词：防止把虚拟环境、缓存和快照文件本身扫进去（防止无限套娃）"""
    ignore_patterns = ['__pycache__', '.venv', 'venv', 'node_modules', '.git', '.idea', 'logs']
    
    # 检查路径的任何一部分是否在黑名单中
    if any(pattern in path.parts for pattern in ignore_patterns):
        return True
    # 绝对禁止读取生成的快照本身
    if path.name == 'project_snapshot.md':
        return True
    return False


def scan_directory_tree(root_path: Path) -> str:
    """生成漂亮的目录树"""
    tree_lines = []
    
    def build_tree(path: Path, prefix: str = "", is_last: bool = True):
        if should_ignore(path):
            return
            
        items = sorted([item for item in path.iterdir() if not should_ignore(item)])
        
        filtered_items = []
        for item in items:
            if item.is_file() and item.suffix in ['.py', '.md', '.jsonl']:  # 支持未来探查jsonl数据源
                filtered_items.append(item)
            elif item.is_dir():
                has_relevant = any(
                    sub.suffix in ['.py', '.md'] 
                    for sub in item.rglob('*') 
                    if sub.is_file() and not should_ignore(sub)
                )
                if has_relevant:
                    filtered_items.append(item)
                    
        for i, item in enumerate(filtered_items):
            is_last_item = i == len(filtered_items) - 1
            current_prefix = "└── " if is_last_item else "├── "
            tree_lines.append(f"{prefix}{current_prefix}{item.name}")
            
            if item.is_dir():
                extension = "    " if is_last_item else "│   "
                build_tree(item, prefix + extension, is_last_item)
                
    tree_lines.append("📁 项目目录树结构:")
    build_tree(root_path)
    return "\n".join(tree_lines)


def generate_snapshot():
    print("🚀 [系统点火] 开始动态生成全局项目快照...")
    project_root = Path(os.path.abspath(os.path.dirname(__file__)))
    
    snapshot_content = [
        "# 📋 企业级专家数字孪生中台 - 全息物理快照",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**项目路径**: {project_root}\n",
        "## 📂 项目目录结构",
        "```text",
        scan_directory_tree(project_root),
        "```\n",
        "## 🔧 全量核心文件源代码"
    ]
    
    # 动态抓取所有核心代码
    print("📄 正在进行动态文件探针扫描...")
    source_files = []
    for file_path in project_root.rglob('*'):
        if file_path.is_file() and file_path.suffix in ['.py', '.md']:
            if not should_ignore(file_path):
                source_files.append(file_path)
                
    source_files = sorted(source_files)
    
    for file_path in source_files:
        rel_path = file_path.relative_to(project_root)
        print(f"  📖 抓取透传: {rel_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            ext = "python" if file_path.suffix == '.py' else "markdown"
            snapshot_content.extend([
                f"### 📄 {rel_path}",
                f"```{ext}",
                content,
                "```\n"
            ])
        except Exception as e:
            print(f"  ❌ 抓取失败: {rel_path} - {e}")
            
    output_path = project_root / "project_snapshot.md"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(snapshot_content))
        
    print(f"✅ [大盘透传成功] 动态快照已生成! 共抓取 {len(source_files)} 个文件。")


if __name__ == "__main__":
    generate_snapshot()
