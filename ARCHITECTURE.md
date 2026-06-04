# 🏛️ 系统架构与防线图纸 (V2.0 — 多模态与并发无状态中台版)



## 1. 文件调用关系总图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           start_system.py (点火中枢)                         │
│  编排: Ingestion → ETL(手动) → 启动后端 → 启动前端 → 打开浏览器              │
└────────────────┬────────────────────────────────────────────────────────────┘
                 │ 调用 subprocess
                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          api_gateway.py (API 网关)                           │
│  FastAPI 服务, 端口 8088                                                     │
│  POST /api/v1/chat                                                          │
│  POST /api/v1/switch_expert                                                 │
│  POST /api/v1/generate_title                                                │
│  GET  /health                                                               │
└────────────────┬────────────────────────────────────────────────────────────┘
                 │ 实例化并调用
                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    services/agent_engine.py (核心生成引擎)                    │
│  ExpertDigitalTwinAgent.generate_reply()                                    │
│  链路: 意图分诊 → RAG召回 → Prompt组装 → LLM生成                            │
├────────────────┬────────────────┬────────────────┬──────────────────────────┤
│ 调用           │ 调用           │ 调用           │ 调用                     │
▼                ▼                ▼                ▼                          │
┌──────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐      │
│state_    │ │vector_db_    │ │expert_       │ │domain/models.py      │      │
│tracker.py│ │service.py    │ │manager.py    │ │(Pydantic 防腐层)     │      │
│(意图探针) │ │(混合检索引擎) │ │(ExpertManager│ │(数据契约)             │      │
│          │ │Dense+BM25+  │ │ 单例)        │ │                      │      │
│          │ │Rerank)      │ │(专家数据加载器)│ │                      │      │
└──────────┘ └──────────────┘ └──────────────┘ └──────────────────────┘      │

                                                              │               │
                                                              │ 读取          │
                                                              ▼               │
                                                    ┌──────────────────┐      │
                                                    │ data/experts/    │      │
                                                    │ {expert_id}/     │      │
                                                    │  ├─ profile.json │      │
                                                    │  └─ knowledge.json      │
                                                    └──────────────────┘      │
                                                                              │
┌─────────────────────────────────────────────────────────────────────────────┐
│                          web_ui.py (前端界面)                                │
│  Streamlit 服务, 端口 8501                                                   │
│  通过 HTTP 调用 api_gateway.py 的 REST API                                   │
│  通过 import 调用 services/expert_manager.py 获取专家列表                     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    services/etl_pipeline.py (ETL 炼丹流水线)                  │
│  数据流: tools/sharegpt_to_jsonl.py → SemanticChunker → LLMMapNode          │
│          → LLMJudgeReduce → DigitalTwinDistiller → ExpertManager.save       │
│          → HybridSearchEngine.upsert_full_corpus()                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  调用链:                                                                     │
│  etl_pipeline.py → domain/models.py (数据契约)                               │
│                  → services/expert_manager.py (保存专家数据)                  │
│                  → services/vector_db_service.py (向量化入库)                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    tools/sharegpt_to_jsonl.py (数据摄入工具)                  │
│  纯物理拆解: CSV(ShareGPT格式) → data/staging/demo_staging.jsonl             │
│  不依赖任何 LLM, 纯 json.loads() + 正则暴力提取                               │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    domain/models.py (领域模型/数据契约)                        │
│  DigitalTwinProfile  - 专家画像模型 (含 Pydantic 校验)                       │
│  KnowledgeChunk      - 知识切片模型                                          │
│  ProbeState          - 探针状态模型                                          │
│  被所有 services 模块引用, 是系统的防腐层                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心接口契约 (API Gateway)

### 2.1 聊天接口
- **Endpoint**: `POST /api/v1/chat`
- **Request** (`ChatRequest`):
  ```json
  {
    "expert_id": "str (多租户路由键，可选，不传自动降级为默认专家)",
    "user_query": "str (业务咨询/技术报障)",
    "session_history": "[{'role': 'user/assistant', 'content': '...'}]",
    "temperature": 0.7,
    "frequency_penalty": 0.2,
    "presence_penalty": 0.2,
    "max_tokens": 500,
    "stop_sequences": ["\nCustomer:", "\nExpert:"]
  }
  ```

- **Response** (`ChatResponse`):
  ```json
  {
    "reply": "str (专家回复)",
    "business_intent": "str (TECHNICAL_SUPPORT/SALES_PITCH/CHIT_CHAT)",
    "urgency_level": "str (高/中/低)",
    "retrieved_memories": "[{text, score(含rerank_score), citation_source, chunk_type}]",
    "prompt_length": 0,
    "generation_time": 0.0
  }
  ```

### 2.2 专家切换接口 (多租户热切换)
- **Endpoint**: `POST /api/v1/switch_expert`
- **Request** (`SwitchExpertRequest`):
  ```json
  {
    "expert_id": "str (目标专家唯一标识)"
  }
  ```
- **Response** (`SwitchExpertResponse`):
  ```json
  {
    "success": true,
    "message": "专家切换成功",
    "expert_name": "金牌架构师"
  }
  ```

### 2.3 标题生成接口
- **Endpoint**: `POST /api/v1/generate_title`
- **Request**: `{"user_query": "str"}`
- **Response**: `{"title": "str (不超过6字)"}`

### 2.4 健康检查
- **Endpoint**: `GET /health`
- **Response**: `{"status": "healthy", "expert_name": "...", "knowledge_base_size": N}`

---

## 3. 核心运转链路 (逐层拆解)

### 3.1 数据摄入 (Ingestion)
| 文件 | 功能 | 调用方 |
|------|------|--------|
| `tools/sharegpt_to_jsonl.py` | 暴力拆解 CSV 中 ShareGPT 格式的 conversations 列 | `start_system.py` (subprocess) |
| `data/staging/demo_staging.jsonl` | 暂存格式 `{"speaker": "客户/专家", "content": "..."}` | 被 ETL 读取 |

**防线**: 纯物理拆解, 不依赖 LLM, 硬编码角色映射 `ROLE_MAP = {"user": "客户", "assistant": "专家"}`

### 3.2 灵魂蒸馏 (ETL)
| 阶段 | 类/函数 | 文件 | 功能 |
|------|---------|------|------|
| 语义切片 | `SemanticChunker` | `services/etl_pipeline.py` | 按完整问答对切分 (10对=20行/块) |
| Map 提取 | `LLMMapNode.extract_chunk()` | `services/etl_pipeline.py` | 并发调用 LLM 提取 QA_PAIR/SOP_STEP/BUSINESS_RULE |
| Reduce 审查 | `LLMJudgeReduce.judge_and_reduce()` | `services/etl_pipeline.py` | 模糊去重(阈值0.85) + 分批压缩(40条/批) |
| 侧写蒸馏 | `DigitalTwinDistiller` | `services/etl_pipeline.py` | 提取专家画像 (含 CoT 思维链 + 金牌话术) |
| 数据保存 | `ExpertManager.save_expert()` | `services/expert_manager.py` | 写入 `data/experts/{expert_id}/` |
| 向量入库 | `HybridSearchEngine.upsert_full_corpus()` | `services/vector_db_service.py` | ChromaDB + BM25 双轨写入 |

**防线**:
- Token 熔断: 超过 500 行数据强制截断
- 物理剥壳机: `_clean_and_parse_json()` 正则提取 JSON, 无视 LLM 废话
- 自省纠错: JSON 解析失败时自动发起第二次 LLM 修复请求
- 0 数据物理熔断锁: 空列表直接返回

### 3.3 意图路由 (Routing)
| 文件 | 类 | 功能 |
|------|----|------|
| `services/state_tracker.py` | `BusinessIntentProbe` | 调用轻量级 LLM (Qwen2.5-7B) 识别业务意图 |
| `domain/models.py` | `ProbeState` | 探针状态模型, 含 business_intent + urgency_level |

**防线**:
- 兜底意图降级: 检测到非法意图时强制降级为 `supported_intents[-1]`
- 算力风控: 兜底意图物理阻断向量检索, 跳过 RAG
- 异常降级: LLM 调用失败时返回 `confidence=0.0` 的兜底意图

### 3.4 混合检索 (Hybrid RAG)
| 文件 | 类 | 功能 |
|------|----|------|
| `services/vector_db_service.py` | `HybridSearchEngine` | Dense(Chroma) + Sparse(BM25) + Reranking 三路召回 |

**检索流程**:
1. **Dense Retrieval**: ChromaDB 向量召回 Top-20 (模型: BAAI/bge-m3)
2. **Sparse Retrieval**: BM25 关键词召回 Top-20 (分词: jieba)
3. **去重合流**: 合并两路结果, 标记双路命中
4. **交叉重排**: BGE-Reranker-V2-M3 精细排序, 返回 Top-3

**防线**:
- 集合级物理隔离: `expert_{id}_memory` 命名空间, 多租户数据不串脑
- 重排降级: 重排 API 失败时返回原始顺序
- 混合检索降级: 无结果时降级到纯向量检索
- **[混合检索降级防线]**: 当 Dense (ChromaDB) 检索故障或重排 API 超时报错时，HybridSearchEngine 内部自动平滑降级为本地 BM25 内存索引检索，严禁裸抛错误，且不依赖任何外部 memory_manager


### 3.5 推理生成 (Generation)
| 文件 | 类/函数 | 功能 |
|------|---------|------|
| `services/agent_engine.py` | `ExpertDigitalTwinAgent.generate_reply()` | 完整生成链路 |
| `services/agent_engine.py` | `_build_rag_system_prompt()` | 神经缝合: 组装专家画像 + 知识切片 + 红线 + CoT |

**Prompt 组装结构**:
1. 专家身份与专业领域
2. 沟通风格 + 金牌话术模板 + 话术使用护栏
3. 业务红线 (绝不可违反)
4. 专家思维链 CoT SOP (反模式坍塌)
5. 路由意图 + 紧急程度
6. 企业知识切片参考
7. RAG 降噪护栏 (无关知识直接无视)
8. 企业级任务指令
9. Golden Few-Shots 金牌示例 (语气校准)
10. **终极反机器味红线** (禁止 Markdown、禁止官腔、禁止 AI 味收尾)

**防线**:
- Fail Fast: 无真实 API 密钥直接抛出致命错误
- 算力风控: 兜底意图物理阻断向量检索
- RAG 降噪护栏: 无关知识直接无视, 严禁强行缝合

---

## 4. 绝对物理防线 (不可破坏)

### 4.1 网关日志写入层
- **位置**: `api_gateway.py` → `write_system_trace()` 函数 (第55-76行)
- **防护目标**: 防止 Windows WinError 32 (文件 I/O 并发死锁) 击穿网关
- **实现**: `try-except` 包裹文件写入操作, 异常时仅打印警告, 不中断请求处理

### 4.2 ChromaDB 集合级物理隔离
- **位置**: `services/vector_db_service.py` → `_get_expert_collection()` 函数 (第124-138行)
- **防护目标**: 防止多租户数据串脑
- **实现**: 每个专家独立集合 `expert_{clean_id}_memory`, 查询时 `where={"expert_id": expert_id}` 过滤

### 4.3 物理剥壳机 (JSON 提取)
- **位置**: `services/etl_pipeline.py` → `_clean_and_parse_json()` (LLMMapNode 和 LLMJudgeReduce 均有)
- **防护目标**: 防止 LLM 输出 Markdown 包装、废话前缀导致 JSON 解析失败
- **实现**: 正则去除 ```json 标记 → 寻找第一个 `{`/`[` 和最后一个 `}`/`]` → 截取纯净 JSON

### 4.4 Token 熔断机制
- **位置**: `services/etl_pipeline.py` → `SemanticChunker.load_and_chunk()` (第124-128行)
- **防护目标**: 防止超大数据集进入 LLM 提纯层导致 Token 爆炸
- **实现**: `MAX_CORPUS_SIZE = 500`, 超过直接截断

### 4.5 算力风控 (意图路由拉闸)
- **位置**: `services/agent_engine.py` → `generate_reply()` (第196-202行)
- **防护目标**: 闲聊意图物理阻断向量检索, 节省算力
- **实现**: 判断 `business_intent == fallback_intent` 时跳过 RAG

### 4.6 反 LLM 谄媚机制
- **位置**: `domain/models.py` → `DigitalTwinProfile.clean_llm_fluff()` (第110-143行)
- **防护目标**: 清洗大模型生成的解释性废话 (如"从对话中可以看出...")
- **实现**: 正则匹配并删除 10 种常见 LLM 废话模式

### 4.7 防破产机制 (ETL 手动确认)
- **位置**: `start_system.py` → `prompt_etl_confirmation()` (第132-152行)
- **防护目标**: 防止自动执行高成本 ETL 流程导致 Token 费用失控
- **实现**: ETL 阶段必须由指挥官手动执行 `python services/etl_pipeline.py`

### 4.8 多租户热切换闭环
- **位置**: `web_ui.py` (第338-356行) + `api_gateway.py` (第329-382行)
- **防护目标**: 前端切换专家时, 确保网关同步切换, 防止数据错乱
- **实现**: 前端检测 expert_id 变化 → 调用 `/api/v1/switch_expert` → 网关重新初始化 Agent → 前端清空会话

---

## 5. 数据存储结构

```
data/
├── chroma_db/                    # ChromaDB 持久化向量数据库
│   └── (ChromaDB 内部文件)
├── experts/                      # 多租户专家池 (物理隔离)
│   └── {expert_id}/
│       ├── profile.json          # 专家画像 (DigitalTwinProfile)
│       ├── knowledge.json        # 知识库 (KnowledgeChunk[])
│       └── bm25_index.pkl        # BM25 关键词索引
├── raw/
│   └── source_data.csv           # 原始脏数据 (ShareGPT 格式)
├── staging/
│   └── demo_staging.jsonl        # 暂存格式 (sharegpt_to_jsonl.py 输出)
└── sessions/                     # 会话历史
    └── {expert_id}/
        └── {session_id}.json     # 单次会话数据
logs/
└── system_trace.log              # 系统追踪日志 (JSONL)
```

---

## 6. 技术栈

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| API 框架 | FastAPI + Uvicorn | RESTful 网关 (端口 8088) |
| 前端 | Streamlit | B 端业务沙盘 (端口 8501) |
| 向量数据库 | ChromaDB (PersistentClient) | 语义检索 |
| 关键词检索 | BM25Okapi (rank_bm25) | 稀疏检索 |
| 重排模型 | BAAI/bge-reranker-v2-m3 | 交叉重排 |
| Embedding 模型 | BAAI/bge-m3 | 文本向量化 |
| 大模型 | DeepSeek-V3 (生成) / Qwen2.5-72B (ETL) / Qwen2.5-7B (意图探针) | 多模型分工 |
| 数据校验 | Pydantic V2 | 防腐层 |
| 重试机制 | tenacity (指数退避) | 网络容错 |
| 分词 | jieba | 中文分词 (BM25) |
