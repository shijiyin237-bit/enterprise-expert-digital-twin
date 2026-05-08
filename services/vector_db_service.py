"""
企业级向量数据库服务 - Enterprise Vector Database Service
B 端专家数字孪生系统的物理向量引擎
使用 ChromaDB 本地向量数据库 + BGE-m3 Embedding API
"""

import json
import os
import time
from typing import List, Dict, Any
from dotenv import load_dotenv
import openai
import chromadb
from chromadb.config import Settings
from tenacity import retry, wait_exponential, stop_after_attempt

# 加载环境变量
load_dotenv()

# [核心节点]：B 端企业级命名规范
CLIENT_NAME = os.getenv("CLIENT_NAME", "客户")
EXPERT_NAME = os.getenv("EXPERT_NAME", "专家")

# [核心节点]：导入企业级数据契约
from domain.models import KnowledgeChunk


class ChromaEngine:
    """
    ChromaDB 向量引擎 - 多租户专家池版本
    
    输入：原始语料文件路径、查询文本、专家ID
    输出：向量相似度搜索结果
    副作用：在本地创建持久化向量数据库
    
    用途：对全量原始语料进行向量化入库，支持极速语义检索
    
    [核心节点]：多租户专家池架构 - 通过 expert_id 实现物理级别数据隔离
    每个专家的知识切片在 metadata 中标记 expert_id，检索时强制过滤
    """
    
    def __init__(self):
        """
        初始化向量引擎
        
        输入：无
        输出：ChromaEngine 实例
        副作用：创建或连接本地 ChromaDB 数据库
        """
        # [核心节点]：此处初始化本地向量数据库，物理隔离到 data/chroma_db/
        self.base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        self.chroma_dir = os.path.join(self.base_dir, "data", "chroma_db")
        
        # 确保目录存在
        os.makedirs(self.chroma_dir, exist_ok=True)
        
        # 初始化 ChromaDB 客户端
        self.client = chromadb.PersistentClient(path=self.chroma_dir)
        
        # 创建或获取集合
        self.collection_name = "full_corpus_memory"
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "全量原始语料向量库"}
        )
        
        # 初始化 Embedding 客户端
        self.api_key = os.getenv("SILICONFLOW_API_KEY")
        self.base_url = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")
        self.embedding_model = "BAAI/bge-m3"
        
        if not self.api_key:
            raise ValueError("致命错误：未检测到 SILICONFLOW_API_KEY")
        
        self.embedding_client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        print(f"[+] ChromaEngine 初始化完成")
        print(f"    - 数据库路径: {self.chroma_dir}")
        print(f"    - 集合名称: {self.collection_name}")
        print(f"    - Embedding 模型: {self.embedding_model}")
    
    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(4))
    def _get_embedding(self, text: str) -> List[float]:
        """
        调用 Embedding API 获取文本向量
        
        输入：待向量化的文本
        输出：向量列表（浮点数数组）
        副作用：调用外部 API
        
        原理：使用 SiliconFlow 的 BAAI/bge-m3 模型生成高精度向量
        
        [核心节点]：使用 tenacity 实现指数退避重试，解决 API QPS 限流问题
        重试策略：初始等待2秒，指数增长，最大10秒，最多重试4次
        """
        # [核心节点]：此处调用 SiliconFlow Embedding API 生成向量，带自动重试机制
        try:
            response = self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"[!] Embedding 调用失败，触发自动重试: {e}")
            raise
    
    def upsert_full_corpus(self, expert_id: str, knowledge_base: List[KnowledgeChunk] = None):
        """
        [核心节点]：企业级知识切片向量化入库（多租户版本）
        
        输入：
            - expert_id: 专家唯一标识（租户隔离键）
            - knowledge_base: 企业级知识切片列表（由 ETL 环节清洗完毕的标准 JSON 结构）
        输出：无
        副作用：向本地 ChromaDB 向量数据库批量插入数据
        
        原理：直接读取 ETL 输出的 KnowledgeChunk -> 向量化 -> 批量入库
              [工程红线]：B 端切片已在 ETL 环节完成，向量引擎不再重复切片
        
        [核心节点]：多租户隔离 - 每个 chunk 的 metadata 中强制写入 expert_id
        """
        # [物理切除]：_chunk_raw_data 方法已物理删除 - B 端企业系统不需要原始语料切片
        
        if knowledge_base is None:
            # [降级方案]：尝试从本地 JSON 文件加载
            kb_path = os.path.join(self.base_dir, "data", "enterprise_knowledge_base.json")
            if not os.path.exists(kb_path):
                raise FileNotFoundError(f"知识库文件不存在: {kb_path}，请提供 knowledge_base 参数")
            
            print(f"[+] 正在从本地加载企业知识库: {kb_path}")
            with open(kb_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                knowledge_base = [KnowledgeChunk(**item) for item in data]
        
        if not knowledge_base:
            print(f"[!] 知识库为空，跳过入库")
            return
        
        print(f"\n{'='*80}")
        print(f"[核心节点]：开始企业级知识切片向量化入库")
        print(f"{'='*80}")
        print(f"[+] 知识切片总数: {len(knowledge_base)}")
        
        # [核心节点]：批量入库
        batch_size = 10
        total_chunks = len(knowledge_base)
        
        for i in range(0, total_chunks, batch_size):
            batch = knowledge_base[i:i+batch_size]
            batch_end = min(i + batch_size, total_chunks)
            
            print(f"[+] 正在向量化第 {i+1}-{batch_end} 个知识切片 (共 {total_chunks} 个)...")
            
            ids = []
            embeddings = []
            documents = []
            metadatas = []
            
            for idx, chunk in enumerate(batch):
                chunk_id = f"kb_chunk_{i+idx}"
                ids.append(chunk_id)
                
                # [核心节点]：使用 chunk.content 作为向量化输入
                try:
                    embedding = self._get_embedding(chunk.content)
                    embeddings.append(embedding)
                except Exception as e:
                    print(f"[!] 跳过知识切片 {chunk_id} 向量化失败: {e}")
                    continue
                
                # [核心节点]：存储原始内容
                documents.append(chunk.content)
                
                # [核心节点]：多租户隔离 - 强制写入 expert_id 到 metadata
                metadatas.append({
                    "expert_id": expert_id,  # [核心节点]：租户隔离键，物理级别数据隔离
                    "chunk_type": chunk.chunk_type,
                    "citation_source": chunk.citation_source,
                    "upstream_file": chunk.upstream_file if hasattr(chunk, 'upstream_file') else "",
                    "doc_id": chunk.doc_id if hasattr(chunk, 'doc_id') else ""
                })
            
            # 批量插入
            if embeddings:
                try:
                    self.collection.add(
                        ids=ids[:len(embeddings)],
                        embeddings=embeddings,
                        documents=documents[:len(embeddings)],
                        metadatas=metadatas[:len(embeddings)]
                    )
                    print(f"    ✓ 成功入库 {len(embeddings)} 个向量")
                except Exception as e:
                    print(f"[!] 批量入库失败: {e}")
                    continue
            
            # [核心节点]：物理缓冲，防止打穿 API QPS 限制
            time.sleep(0.5)
        
        print(f"\n[+] 企业级知识切片向量化入库完成！")
        print(f"    - 总切片数: {total_chunks}")
        print(f"    - 数据库路径: {self.chroma_dir}（保持不变）")
        print(f"    - 集合名称: {self.collection_name}")
        print(f"    - Embedding 模型: BAAI/bge-m3（保持不变）")
    
    def coarse_search(self, query: str, expert_id: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        [核心节点]：企业级知识切片向量检索（多租户版本）
        
        输入：
            - query: 自然语言查询文本
            - expert_id: 专家唯一标识（租户隔离过滤键）
            - top_k: 返回数量（B 端默认 3 条）
        输出：最相关的知识切片列表，每个元素为包含 text 和 metadata 的字典
        副作用：无
        
        原理：将查询向量化，在向量空间中检索最相似的文本块
              [核心节点]：强制使用 where={"expert_id": expert_id} 实现物理级别数据隔离
              返回格式必须与 agent_engine.py 中的组装逻辑兼容
        """
        # [核心节点]：此处执行向量相似度检索
        print(f"[+] 正在执行企业级知识切片检索: {query}")
        
        # 获取查询向量
        try:
            query_embedding = self._get_embedding(query)
        except Exception as e:
            print(f"[!] 查询向量化失败: {e}")
            return []
        
        # 执行检索（多租户隔离）
        try:
            # [核心节点]：强制使用 expert_id 过滤，实现物理级别数据隔离
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"expert_id": expert_id}  # [核心节点]：租户隔离过滤条件
            )
            print(f"[+] 专家 {expert_id} 向量检索完成")
        except Exception as e:
            print(f"[!] 向量检索失败: {e}")
            return []
        
        # [核心节点]：格式化结果 - 必须包含 text 和 metadata 键
        formatted_results = []
        if results['ids'] and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                # [核心节点]：组装返回格式，与 agent_engine.py 兼容
                result_item = {
                    "id": doc_id,
                    "text": results['documents'][0][i] if results['documents'] else "",
                    "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                    "distance": results['distances'][0][i] if results['distances'] else 0.0
                }
                formatted_results.append(result_item)
        
        print(f"[+] 企业级知识切片检索完成，返回 {len(formatted_results)} 个结果")
        return formatted_results


if __name__ == "__main__":
    """
    主程序：执行企业级知识切片向量入库测试
    """
    # [核心节点]：设置环境变量，实现架构回归
    os.environ["FORCE_ETL_REBUILD"] = "1"
    
    print("="*80)
    print("企业级向量数据库引擎 - B端专家数字孪生系统")
    print("="*80)
    
    try:
        # 初始化引擎
        engine = ChromaEngine()
        
        # [核心节点]：执行企业级知识切片入库
        engine.upsert_full_corpus()
        
        # 测试检索
        print(f"\n{'='*80}")
        print(f"测试企业级知识切片检索")
        print(f"{'='*80}")
        
        test_query = "电脑故障"
        search_results = engine.coarse_search(test_query, top_k=3)
        
        print(f"\n查询: {test_query}")
        print(f"结果数: {len(search_results)}")
        for idx, result in enumerate(search_results, 1):
            print(f"\n--- 结果 {idx} ---")
            print(f"相似度: {result['distance']:.4f}")
            print(f"切片类型: {result['metadata'].get('chunk_type', 'N/A')}")
            print(f"来源: {result['metadata'].get('citation_source', 'N/A')}")
            print(f"内容预览: {result['text'][:200]}...")
        
        print(f"\n[+] 企业级向量数据库测试完成！")
        
    except Exception as e:
        print(f"[!] 执行失败: {e}")
        import traceback
        traceback.print_exc()
