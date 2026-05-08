#!/usr/bin/env python3
"""
项目快照生成器 - Project Snapshot Generator
用于架构交接，生成完整的项目上下文快照
"""

import os
from pathlib import Path
from datetime import datetime


def scan_directory_tree(root_path: str) -> str:
    """
    扫描项目目录树结构，仅包含.py和.md文件
    
    Args:
        root_path: 项目根目录路径
        
    Returns:
        格式化的目录树字符串
    """
    tree_lines = []
    root = Path(root_path)
    
    def should_ignore(path: Path) -> bool:
        """判断是否应该忽略该路径"""
        ignore_patterns = ['__pycache__', '.venv', 'node_modules', '.git']
        return any(pattern in str(path) for pattern in ignore_patterns)
    
    def build_tree(path: Path, prefix: str = "", is_last: bool = True):
        """递归构建目录树"""
        if should_ignore(path):
            return
            
        # 获取子目录和文件，排序
        items = sorted([item for item in path.iterdir() if not should_ignore(item)])
        
        # 过滤出.py和.md文件
        filtered_items = []
        for item in items:
            if item.is_file() and item.suffix in ['.py', '.md']:
                filtered_items.append(item)
            elif item.is_dir():
                # 检查目录下是否有.py或.md文件
                has_relevant_files = any(
                    sub_item.suffix in ['.py', '.md'] 
                    for sub_item in item.rglob('*') 
                    if sub_item.is_file()
                )
                if has_relevant_files:
                    filtered_items.append(item)
        
        for i, item in enumerate(filtered_items):
            is_last_item = i == len(filtered_items) - 1
            current_prefix = "└── " if is_last_item else "├── "
            tree_lines.append(f"{prefix}{current_prefix}{item.name}")
            
            if item.is_dir():
                extension = "    " if is_last_item else "│   "
                build_tree(item, prefix + extension, is_last_item)
    
    tree_lines.append("📁 项目目录树结构 (.py/.md 仅显示):")
    build_tree(root)
    return "\n".join(tree_lines)


def read_file_content(file_path: str) -> str:
    """
    读取文件内容
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件内容字符串
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"❌ 读取文件失败: {e}"


def generate_snapshot():
    """
    生成项目快照
    """
    print("🚀 开始生成项目快照...")
    
    # 项目根目录
    project_root = os.path.dirname(os.path.abspath(__file__))
    
    # 核心文件列表
    core_files = [
        "domain/models.py",
        "api_gateway.py", 
        "services/agent_engine.py",
        "services/state_tracker.py",
        "web_ui.py",
        "engineering_norms.md"
    ]
    
    # 构建快照内容
    snapshot_content = []
    
    # 添加头部信息
    snapshot_content.append("# 📋 企业级专家数字孪生中台 - 项目快照")
    snapshot_content.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    snapshot_content.append(f"**项目路径**: {project_root}")
    snapshot_content.append("")
    
    # 添加目录树
    print("📂 扫描项目目录树...")
    directory_tree = scan_directory_tree(project_root)
    snapshot_content.append("## 📂 项目目录结构")
    snapshot_content.append("```")
    snapshot_content.append(directory_tree)
    snapshot_content.append("```")
    snapshot_content.append("")
    
    # 添加核心文件内容
    print("📄 读取核心文件内容...")
    snapshot_content.append("## 🔧 核心文件源代码")
    
    for file_path in core_files:
        full_path = os.path.join(project_root, file_path)
        if os.path.exists(full_path):
            print(f"  📖 读取: {file_path}")
            content = read_file_content(full_path)
            
            snapshot_content.append(f"### 📄 {file_path}")
            snapshot_content.append("```" + ("python" if file_path.endswith('.py') else "markdown"))
            snapshot_content.append(content)
            snapshot_content.append("```")
            snapshot_content.append("")
        else:
            print(f"  ⚠️ 文件不存在: {file_path}")
            snapshot_content.append(f"### 📄 {file_path}")
            snapshot_content.append("❌ 文件不存在")
            snapshot_content.append("")
    
    # 写入快照文件
    output_path = os.path.join(project_root, "project_snapshot.md")
    print("💾 生成快照文件...")
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(snapshot_content))
        
        file_size = os.path.getsize(output_path)
        print(f"✅ 快照生成成功!")
        print(f"📁 输出文件: {output_path}")
        print(f"📊 文件大小: {file_size} 字节")
        
    except Exception as e:
        print(f"❌ 生成快照失败: {e}")


if __name__ == "__main__":
    generate_snapshot()
