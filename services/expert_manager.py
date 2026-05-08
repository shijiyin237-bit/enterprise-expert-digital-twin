"""
专家管理器 - Expert Manager
多租户专家池架构的核心管理组件

用途：
1. 管理 data/experts/ 目录下的所有专家数据
2. 提供专家列表查询、保存、加载等功能
3. 为每个专家维护独立的 Profile 和 KnowledgeBase

[核心节点]：多租户专家池的物理隔离层，每个专家拥有独立的数据空间
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# [核心节点]：导入领域模型，确保数据契约一致性
from domain.models import DigitalTwinProfile, KnowledgeChunk


class ExpertManager:
    """
    专家管理器
    
    [核心节点]：负责管理多租户专家池的所有生命周期操作
    包括：列出所有专家、保存新专家、加载专家数据、删除专家等
    
    数据存储结构：
    data/experts/
    ├── {expert_id}/
    │   ├── profile.json      # 专家画像
    │   └── knowledge.json    # 知识库
    └── ...
    """
    
    def __init__(self, base_dir: str = "data/experts"):
        """
        初始化专家管理器
        
        输入：专家数据根目录路径
        输出：ExpertManager 实例
        
        [核心节点]：自动创建目录结构，确保存储路径可用
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        print(f"[ExpertManager] 初始化完成，专家数据目录: {self.base_dir}")
    
    def _get_expert_dir(self, expert_id: str) -> Path:
        """
        获取指定专家的专属目录
        
        [核心节点]：每个专家拥有独立的子目录，实现物理隔离
        """
        expert_dir = self.base_dir / expert_id
        expert_dir.mkdir(parents=True, exist_ok=True)
        return expert_dir
    
    def list_experts(self) -> List[Dict[str, Any]]:
        """
        列出所有已存在的专家
        
        输出：专家列表，包含 expert_id、expert_name 等基本信息
        
        [核心节点]：动态扫描目录，实时反映当前专家池状态
        """
        experts = []
        
        try:
            # 遍历 experts 目录下的所有子目录
            for expert_dir in self.base_dir.iterdir():
                if expert_dir.is_dir():
                    expert_id = expert_dir.name
                    profile_path = expert_dir / "profile.json"
                    
                    if profile_path.exists():
                        try:
                            with open(profile_path, 'r', encoding='utf-8') as f:
                                profile_data = json.load(f)
                            
                            experts.append({
                                "expert_id": expert_id,
                                "expert_name": profile_data.get("expert_name", "未命名专家"),
                                "domain_expertise": profile_data.get("domain_expertise", "未知领域"),
                                "created_at": profile_data.get("created_at", "未知")
                            })
                        except Exception as e:
                            print(f"[!] 读取专家 {expert_id} 画像失败: {e}")
                            continue
        except Exception as e:
            print(f"[!] 扫描专家目录失败: {e}")
        
        return experts
    
    def save_expert(
        self,
        expert_id: str,
        profile: DigitalTwinProfile,
        knowledge_base: List[KnowledgeChunk]
    ) -> bool:
        """
        保存专家数据（画像 + 知识库）
        
        输入：
            - expert_id: 专家唯一标识
            - profile: 专家画像对象
            - knowledge_base: 知识切片列表
        
        输出：保存成功返回 True，失败返回 False
        
        [核心节点]：结构化存储，每个专家独立目录，物理隔离
        """
        try:
            expert_dir = self._get_expert_dir(expert_id)
            
            # 保存专家画像
            profile_path = expert_dir / "profile.json"
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile.model_dump(), f, ensure_ascii=False, indent=2)
            print(f"[+] 专家画像已保存: {profile_path}")
            
            # 保存知识库
            knowledge_path = expert_dir / "knowledge.json"
            knowledge_data = [chunk.model_dump() for chunk in knowledge_base]
            with open(knowledge_path, 'w', encoding='utf-8') as f:
                json.dump(knowledge_data, f, ensure_ascii=False, indent=2)
            print(f"[+] 知识库已保存: {knowledge_path}")
            
            print(f"[+] 专家 {expert_id} ({profile.expert_name}) 数据保存成功")
            return True
            
        except Exception as e:
            print(f"[!] 保存专家 {expert_id} 数据失败: {e}")
            return False
    
    def load_expert(self, expert_id: str) -> Optional[Tuple[DigitalTwinProfile, List[KnowledgeChunk]]]:
        """
        加载指定专家的完整数据
        
        输入：expert_id
        输出：(profile, knowledge_base) 元组，或 None（如果不存在）
        
        [核心节点]：动态加载，支持运行时切换专家
        """
        expert_dir = self._get_expert_dir(expert_id)
        profile_path = expert_dir / "profile.json"
        knowledge_path = expert_dir / "knowledge.json"
        
        # 检查专家是否存在
        if not profile_path.exists():
            print(f"[!] 专家 {expert_id} 不存在")
            return None
        
        try:
            # 加载专家画像
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
            profile = DigitalTwinProfile(**profile_data)
            print(f"[+] 专家画像加载成功: {profile.expert_name}")
            
            # 加载知识库
            knowledge_base = []
            if knowledge_path.exists():
                with open(knowledge_path, 'r', encoding='utf-8') as f:
                    knowledge_data = json.load(f)
                
                for item in knowledge_data:
                    try:
                        chunk = KnowledgeChunk(**item)
                        knowledge_base.append(chunk)
                    except Exception as e:
                        print(f"[!] 知识切片加载失败，跳过: {e}")
                        continue
                
                print(f"[+] 知识库加载成功: {len(knowledge_base)} 条切片")
            else:
                print(f"[!] 专家 {expert_id} 知识库不存在")
            
            return profile, knowledge_base
            
        except Exception as e:
            print(f"[!] 加载专家 {expert_id} 数据失败: {e}")
            return None
    
    def delete_expert(self, expert_id: str) -> bool:
        """
        删除指定专家及其所有数据
        
        [核心节点]：物理删除，清理存储空间
        """
        import shutil
        
        expert_dir = self.base_dir / expert_id
        
        if not expert_dir.exists():
            print(f"[!] 专家 {expert_id} 不存在，无法删除")
            return False
        
        try:
            shutil.rmtree(expert_dir)
            print(f"[+] 专家 {expert_id} 已删除")
            return True
        except Exception as e:
            print(f"[!] 删除专家 {expert_id} 失败: {e}")
            return False
    
    def generate_expert_id(self, expert_name: str) -> str:
        """
        生成专家唯一标识
        
        输入：专家名称
        输出：expert_id（拼音或UUID格式）
        
        [核心节点]：基于名称生成易读的ID，同时保证唯一性
        """
        import re
        from datetime import datetime
        
        # 将中文名转换为拼音风格（简单处理：保留字母和数字）
        base_id = re.sub(r'[^\w\u4e00-\u9fff]', '', expert_name.lower())
        
        # 如果是中文，使用拼音首字母（这里简化处理，实际可用 pypinyin 库）
        if re.search(r'[\u4e00-\u9fff]', base_id):
            # 简单映射常见中文字符
            char_map = {
                '金牌': 'jinpai', '客服': 'kefu', '专家': 'zhuanjia',
                '架构': 'jiagou', '销售': 'xiaoshou', '技术': 'jishu',
                '售前': 'shouqian', '售后': 'shouhou', '客服': 'kefu'
            }
            for cn, py in char_map.items():
                base_id = base_id.replace(cn, py)
            # 移除剩余中文字符
            base_id = re.sub(r'[\u4e00-\u9fff]', '', base_id)
        
        # 添加时间戳确保唯一性
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        expert_id = f"{base_id}_{timestamp}" if base_id else f"expert_{timestamp}"
        
        # 确保不超过合理长度
        if len(expert_id) > 50:
            expert_id = expert_id[:50] + f"_{timestamp}"
        
        return expert_id


# 单例模式，全局共享一个 ExpertManager 实例
_expert_manager_instance = None


def get_expert_manager() -> ExpertManager:
    """
    获取 ExpertManager 单例实例
    
    [核心节点]：全局共享，避免重复创建
    """
    global _expert_manager_instance
    if _expert_manager_instance is None:
        _expert_manager_instance = ExpertManager()
    return _expert_manager_instance


if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("ExpertManager 测试")
    print("=" * 60)
    
    manager = ExpertManager()
    
    # 列出所有专家
    experts = manager.list_experts()
    print(f"\n[+] 当前共有 {len(experts)} 个专家")
    for exp in experts:
        print(f"    - {exp['expert_id']}: {exp['expert_name']} ({exp['domain_expertise']})")
    
    # 测试生成 ID
    print(f"\n[+] ID 生成测试:")
    print(f"    '金牌客服' -> {manager.generate_expert_id('金牌客服')}")
    print(f"    '售前专家' -> {manager.generate_expert_id('售前专家')}")
