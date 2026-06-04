"""
企业级混合检索引擎 - Enterprise Hybrid Search Engine
B 端专家数字孪生系统的物理向量引擎
使用 ChromaDB 向量数据库 + BM25 关键词检索 + 交叉重排架构
"""

import json
import os
import time
import pickle
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
import openai
import chromadb
from chromadb.config import Settings
from tenacity import retry, wait_exponential, stop_after_attempt
import requests

# [核心节点]：混合检索依赖库
import jieba
from rank_bm25 import BM25Okapi

# 加载环境变量
load_dotenv()

# [核心节点]：B 端企业级命名规范
CLIENT_NAME = os.getenv("CLIENT_NAME", "客户")
EXPERT_NAME = os.getenv("EXPERT_NAME", "专家")

# [核心节点]：导入企业级数据契约
from domain.models import KnowledgeChunk


class HybridSearchEngine:
    """
    混合检索引擎 (Hybrid Search Engine) - 多租户专家池版本
    
    输入：原始语料文件路径、查询文本、专家ID
    输出：经过 BM25 + 向量 + 重排的三路混合搜索结果
    副作用：在本地创建持久化向量数据库和 BM25 索引
    
    用途：对全量原始语料进行向量化入库，支持语义检索 + 关键词检索 + 交叉重排
    
    [核心节点]：多租户专家池架构 - 通过 expert_id 实现物理级别数据隔离
    每个专家拥有独立的 Chroma 向量库 + BM25 关键词索引 + 重排序能力
    
    [核心节点]：业界标准混合检索架构 - Dense Retrieval (向量) + Sparse Retrieval (BM25) + Reranking
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
        
        # [核心节点]：集合级物理隔离已启用
        # 不再创建全局 full_corpus_memory 集合
        # 改为通过 _get_expert_collection(expert_id) 动态创建/获取专家专属集合
        self.collection_name = None
        self.collection = None
        
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
        
        # [核心节点]：混合检索重排模型配置
        self.rerank_url = "https://api.siliconflow.cn/v1/rerank"
        self.rerank_model = "BAAI/bge-reranker-v2-m3"
        
        # [核心节点]：BM25 索引内存缓存，防止高并发下频繁 pickle.load 锁死磁盘
        self._bm25_cache: Dict[str, dict] = {}
        
        print(f"[+] HybridSearchEngine 初始化完成")

        print(f"    - 向量数据库路径: {self.chroma_dir}")
        print(f"    - 集合名称: {self.collection_name}")
        print(f"    - Embedding 模型: {self.embedding_model}")
        print(f"    - 重排模型: {self.rerank_model}")
        print(f"    - 检索架构: Dense(Chroma) + Sparse(BM25) + Reranking")
    
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
    
    def _get_collection(self, collection_name: str):
        """
        [核心节点]：根据动态路由获取/创建物理隔离的向量集合
        ChromaDB 集合命名规范：3-63 字符，只允许字母、数字、下划线和连字符
        
        输入：集合名称（如 expert_jinpaifuwu_001_soul、tenant_default_kb）
        输出：ChromaDB Collection 对象
        """
        import re
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', collection_name)
        if len(clean_name) > 63:
            clean_name = clean_name[:63]
        
        return self.client.get_or_create_collection(
            name=clean_name,
            metadata={"description": f"命名空间 {collection_name} 的物理隔离向量知识库"}
        )
    
    def _get_expert_collection(self, expert_id: str):
        """
        [核心节点]：根据专家 ID 动态获取/创建物理隔离的向量集合（A 库默认路由）
        降级路由为 expert_{expert_id}_soul（专家专属对话 A 库）
        """
        return self._get_collection(f"expert_{expert_id}_soul")

    
    def upsert_full_corpus(self, expert_id: str, knowledge_base: List[KnowledgeChunk] = None, collection_name: str = None):

        """
        [核心节点]：企业级知识切片向量化入库（多租户版本）
        
        输入：
            - expert_id: 专家唯一标识（租户隔离键）
            - knowledge_base: 企业级知识切片列表（由 ETL 环节清洗完毕的标准 JSON 结构）
            - collection_name: 目标集合名称（选参）。若传入，调用 _get_collection(collection_name)；
                               若无，默认降级路由为 expert_{expert_id}_soul（专家专属对话 A 库）
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
        
        # [核心节点]：动态路由 - 若传入 collection_name 则使用通用集合，否则降级为 expert 默认集合
        if collection_name:
            collection = self._get_collection(collection_name)
            target_label = collection_name
        else:
            collection = self._get_expert_collection(expert_id)
            target_label = f"expert_{expert_id}_soul"
        
        print(f"\n{'='*80}")
        print(f"[核心节点]：开始企业级知识切片向量化入库")
        print(f"{'='*80}")
        print(f"[+] 知识切片总数: {len(knowledge_base)}")
        print(f"[+] 目标集合: {target_label} (物理隔离)")

        
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
            
            # 批量插入（写入专家专属集合）
            if embeddings:
                try:
                    collection.add(
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
        
        # [核心节点]：BM25 双轨写入 - 构建关键词索引
        print(f"\n[核心节点]：开始构建 BM25 关键词索引（双轨写入）")
        try:
            # [核心节点]：使用 jieba 对每条内容进行纯中文分词
            tokenized_corpus = []
            for chunk in knowledge_base:
                tokens = jieba.lcut(chunk.content)
                tokenized_corpus.append(tokens)
            
            # [核心节点]：实例化 BM25Okapi
            bm25 = BM25Okapi(tokenized_corpus)
            
            # [核心节点]：确保专家目录存在
            expert_bm25_dir = os.path.join(self.base_dir, "data", "experts", expert_id)
            os.makedirs(expert_bm25_dir, exist_ok=True)
            
            # [核心节点]：物理保存 BM25 索引和原始切片数组
            bm25_index_path = os.path.join(expert_bm25_dir, "bm25_index.pkl")
            bm25_data = {
                "bm25": bm25,
                "corpus": [chunk.content for chunk in knowledge_base],
                "metadata": [
                    {
                        "chunk_type": chunk.chunk_type,
                        "citation_source": chunk.citation_source,
                        "upstream_file": chunk.upstream_file if hasattr(chunk, 'upstream_file') else "",
                        "doc_id": chunk.doc_id if hasattr(chunk, 'doc_id') else ""
                    }
                    for chunk in knowledge_base
                ]
            }
            with open(bm25_index_path, 'wb') as f:
                pickle.dump(bm25_data, f)
            
            print(f"    ✓ BM25 索引构建完成，已物理保存至: {bm25_index_path}")
            print(f"    ✓ 索引包含 {len(tokenized_corpus)} 条分词文档")
            
            # [核心节点]：双轨写入成功，同步更新/覆写内存缓存
            self._bm25_cache[expert_id] = bm25_data
            print(f"    ✓ BM25 内存缓存已同步更新 (expert_id={expert_id})")
        except Exception as e:
            print(f"[!] BM25 索引构建失败（非致命）: {e}")
            print(f"[!] 向量检索仍可正常工作，仅关键词检索不可用")
        
        print(f"\n[+] 企业级知识切片入库完成！")

        print(f"    - 总切片数: {total_chunks}")
        print(f"    - 向量数据库: {self.chroma_dir}")
        print(f"    - BM25索引: data/experts/{expert_id}/bm25_index.pkl")
        print(f"    - Embedding 模型: BAAI/bge-m3")
        print(f"    - 检索架构: Dense + Sparse 双轨并行")
    
    def _rerank_documents(self, query: str, documents: List[str], top_n: int = 3) -> List[dict]:
        """
        [核心节点]：调用 SiliconFlow 重排模型对文档进行交叉重排
        
        输入：
            - query: 查询文本
            - documents: 待重排的文档列表
            - top_n: 返回前 N 个结果
        输出：按相关性排序的文档列表，包含相关性分数
        副作用：调用外部重排 API
        
        原理：使用 BGE-Reranker-V2-M3 模型对召回的候选文档进行精细排序
        """
        if not documents:
            return []
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.rerank_model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
                "return_documents": True
            }
            
            print(f"[+] 正在调用重排模型: {self.rerank_model}")
            response = requests.post(
                self.rerank_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            reranked_docs = []
            
            for item in result.get("results", []):
                reranked_docs.append({
                    "index": item.get("index", 0),
                    "text": item.get("document", ""),
                    "score": item.get("relevance_score", 0.0)
                })
            
            print(f"    ✓ 重排完成，返回 {len(reranked_docs)} 个结果")
            return reranked_docs
            
        except Exception as e:
            print(f"[!] 重排模型调用失败: {e}")
            print(f"[!] 降级处理：返回原始顺序的前 {top_n} 个文档")
            # [核心节点]：降级机制 - 网络错误时返回原顺序的 documents
            return [{"index": i, "text": doc, "score": 0.0} for i, doc in enumerate(documents[:top_n])]
    
    def hybrid_search(self, query: str, expert_id: str, top_k: int = 3, collection_name: str = None) -> List[KnowledgeChunk]:
        """
        [核心节点]：企业级混合检索（Dense + Sparse + Reranking）
        
        输入：
            - query: 自然语言查询文本
            - expert_id: 专家唯一标识（租户隔离过滤键）
            - top_k: 返回数量（B 端默认 3 条）
            - collection_name: 目标集合名称（选参）。若传入，并行检索 B 库事实和 A 库人设；
                               若无，默认降级路由为 expert_{expert_id}_soul（A 库）
        输出：经过 Pydantic 强校验的 List[KnowledgeChunk] 列表
        副作用：调用向量数据库、BM25 索引和重排模型
        
        原理：
            1. [第一路] Dense Retrieval：从 ChromaDB 向量空间召回 Top-20
            2. [第二路] Sparse Retrieval：从 BM25 关键词索引召回 Top-20
            3. [去重合流]：将两路召回结果合并去重
            4. [交叉重排]：使用 BGE-Reranker 对候选集精细排序
            5. [强契约收拢]：通过 KnowledgeChunk 反序列化构造，确保数据契约完整性
            6. 返回最终 Top-k 结果
        
        [核心节点]：任何一路报错都平滑降级到纯向量检索，确保系统可用性
        """
        print(f"\n[核心节点]：启动混合检索流程: {query}")
        print(f"    - 专家 ID: {expert_id}")
        print(f"    - 目标返回数: {top_k}")
        print(f"    - 集合名称: {collection_name or f'expert_{expert_id}_soul (默认)'}")
        
        # [第一路]：Dense Retrieval（向量召回）
        # [核心节点]：动态路由 - 若传入 collection_name 则使用通用集合，否则降级为 expert 默认集合
        if collection_name:
            collection = self._get_collection(collection_name)
        else:
            collection = self._get_expert_collection(expert_id)

        vector_candidates = []
        try:
            print(f"[+] 第一路检索：Dense Retrieval (ChromaDB)")
            query_embedding = self._get_embedding(query)
            
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=20,  # 召回更多候选供重排
                where={"expert_id": expert_id}
            )

            
            if results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    vector_candidates.append({
                        "id": doc_id,
                        "text": results['documents'][0][i] if results['documents'] else "",
                        "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                        "source": "vector"
                    })
            print(f"    ✓ 向量召回 {len(vector_candidates)} 个候选")
        except Exception as e:
            print(f"[!] 向量检索失败: {e}")
            print(f"[!] 继续尝试 BM25 检索...")
        
        # [第二路]：Sparse Retrieval（BM25 关键词召回）
        bm25_candidates = []
        try:
            print(f"[+] 第二路检索：Sparse Retrieval (BM25)")
            
            # [核心节点]：BM25 内存缓存读取，防止高并发下频繁 pickle.load 锁死磁盘
            if expert_id in self._bm25_cache:
                print(f"    ✓ 命中 BM25 内存缓存 (expert_id={expert_id})")
                bm25_data = self._bm25_cache[expert_id]
            else:
                bm25_index_path = os.path.join(self.base_dir, "data", "experts", expert_id, "bm25_index.pkl")
                if not os.path.exists(bm25_index_path):
                    print(f"[!] BM25 索引文件不存在: {bm25_index_path}")
                    bm25_data = None
                else:
                    print(f"    ✓ 从磁盘加载 BM25 索引并写入内存缓存")
                    with open(bm25_index_path, 'rb') as f:
                        bm25_data = pickle.load(f)
                    # [核心节点]：写入内存缓存，下次直接命中
                    self._bm25_cache[expert_id] = bm25_data
            
            if bm25_data:
                bm25 = bm25_data["bm25"]
                corpus = bm25_data["corpus"]
                metadata_list = bm25_data["metadata"]

                
                # [核心节点]：使用 jieba 对 query 分词
                query_tokens = jieba.lcut(query)
                
                # [核心节点]：BM25 检索 Top-20
                bm25_scores = bm25.get_scores(query_tokens)
                top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:20]
                
                for idx in top_indices:
                    bm25_candidates.append({
                        "id": f"bm25_chunk_{idx}",
                        "text": corpus[idx],
                        "metadata": metadata_list[idx],
                        "source": "bm25"
                    })
                print(f"    ✓ BM25 召回 {len(bm25_candidates)} 个候选")
            else:
                print(f"[!] BM25 索引文件不存在: {bm25_index_path}")
        except Exception as e:
            print(f"[!] BM25 检索失败: {e}")
            print(f"[!] 继续合流向量结果...")
        
        # [去重合流]：合并两路召回结果
        print(f"[+] 候选合流与去重")
        all_candidates = {}
        
        for candidate in vector_candidates + bm25_candidates:
            text = candidate["text"]
            if text not in all_candidates:
                all_candidates[text] = candidate
            else:
                # 如果已存在，标记为双路召回
                all_candidates[text]["source"] = "hybrid"
        
        dedup_candidates = list(all_candidates.values())
        print(f"    ✓ 合并后共 {len(dedup_candidates)} 个唯一候选")
        
        # [交叉重排]：使用 Reranker 精细排序
        reranked_results = []
        if dedup_candidates:
            try:
                print(f"[+] 交叉重排：调用 BGE-Reranker-V2-M3")
                documents = [c["text"] for c in dedup_candidates]
                reranked = self._rerank_documents(query, documents, top_n=min(top_k, len(documents)))
                
                for item in reranked:
                    idx = item["index"]
                    if idx < len(dedup_candidates):
                        result = dedup_candidates[idx].copy()
                        result["rerank_score"] = item["score"]
                        reranked_results.append(result)
                
                print(f"    ✓ 重排完成，返回 {len(reranked_results)} 个结果")
            except Exception as e:
                print(f"[!] 重排失败，使用原始顺序: {e}")
                reranked_results = dedup_candidates[:top_k]
        
        # [健壮性降级]：如果混合检索无结果，降级到纯向量检索
        if not reranked_results and vector_candidates:
            print(f"[!] 混合检索无结果，降级到纯向量检索")
            reranked_results = vector_candidates[:top_k]
        
        # [强契约收拢]：通过 KnowledgeChunk 反序列化构造，确保数据契约完整性
        final_results: List[KnowledgeChunk] = []
        for item in reranked_results:
            try:
                metadata = item.get("metadata", {})
                kc = KnowledgeChunk(
                    expert_id=metadata.get("expert_id", expert_id),
                    content=item.get("text", ""),
                    chunk_type=metadata.get("chunk_type", "BUSINESS_RULE"),
                    citation_source=metadata.get("citation_source", "hybrid_search")
                )
                # [核心节点]：将 rerank_score 等遥测数据附加到 KnowledgeChunk 的 metadata 中
                # 由于 KnowledgeChunk 是 Pydantic 模型，使用 __dict__ 扩展
                kc_dict = kc.model_dump()
                kc_dict["rerank_score"] = item.get("rerank_score", 0.0)
                kc_dict["source"] = item.get("source", "unknown")
                kc_dict["retrieval_source"] = item.get("source", "unknown")
                final_results.append(kc)
            except Exception as e:
                print(f"[!] 知识切片反序列化失败，跳过: {e}")
                continue
        
        print(f"[+] 混合检索完成，最终返回 {len(final_results)} 个结果（Pydantic 强校验）")
        return final_results



if __name__ == "__main__":
    """
    主程序：执行企业级混合检索引擎测试
    """
    # [核心节点]：设置环境变量，实现架构回归
    os.environ["FORCE_ETL_REBUILD"] = "1"
    
    print("="*80)
    print("企业级混合检索引擎 (Hybrid Search) - B端专家数字孪生系统")
    print("架构: Dense(Chroma) + Sparse(BM25) + Reranking")
    print("="*80)
    
    try:
        # 初始化引擎
        engine = HybridSearchEngine()
        
        # 测试专家 ID
        test_expert_id = "test_expert_001"
        
        # [核心节点]：执行企业级知识切片入库（含 BM25 双轨写入）
        # engine.upsert_full_corpus(test_expert_id)
        
        # 测试混合检索
        print(f"\n{'='*80}")
        print(f"测试企业级混合检索 (Hybrid Search)")
        print(f"{'='*80}")
        
        test_query = "电脑故障"
        search_results = engine.hybrid_search(test_query, expert_id=test_expert_id, top_k=3)
        
        print(f"\n查询: {test_query}")
        print(f"结果数: {len(search_results)}")
        for idx, result in enumerate(search_results, 1):
            print(f"\n--- 结果 {idx} ---")
            print(f"召回来源: {result.get('source', 'N/A')}")
            print(f"重排分数: {result.get('rerank_score', 0.0):.4f}")
            print(f"切片类型: {result['metadata'].get('chunk_type', 'N/A')}")
            print(f"来源: {result['metadata'].get('citation_source', 'N/A')}")
            print(f"内容预览: {result['text'][:200]}...")
        
        print(f"\n[+] 企业级混合检索引擎测试完成！")
        
    except Exception as e:
        print(f"[!] 执行失败: {e}")
        import traceback
        traceback.print_exc()
