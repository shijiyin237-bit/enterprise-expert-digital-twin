# 📋 产品需求文档 (PRD) — V2.0

> **企业级数字孪生中台 — 从"单机演示版"到"生产级 Agent 运营中台"**
>
> 本文档定义 V2.0 的完整产品规格、接口契约、模块边界与演进路线。
> 所有需求均基于 V1.0 实际代码能力推导，拒绝空中楼阁。

---

## 1. 产品定位

### 一句话定义
> **一个能"吃下任何企业文档、克隆专家灵魂、动态对接实时数据"的 Agent 运营中台。**

### 目标用户
| 角色 | 使用场景 | 核心诉求 |
|------|---------|---------|
| **B 端业务人员** | 日常客户咨询、技术排障、销售逼单 | 回复像真人专家，有灵魂有语气 |
| **CTO / 技术负责人** | 系统运维、数据监控、知识管理 | 可观测性、数据安全、成本可控 |
| **AI 训练师** | 数据导入、专家训练、效果调优 | 多模态数据摄入、ETL 可视化 |

### 核心差异化 (vs 传统 RAG 中台)
| 维度 | 传统 RAG (FastGPT/Dify) | 本系统 V2.0 |
|------|------------------------|-------------|
| **数据摄入** | 仅支持纯文本/简单 PDF | **多模态版面解析** (PDF/Word/Excel/PPTX → Markdown AST) |
| **专家克隆** | 无，仅知识检索 | **双轨制 ETL**：知识压缩 + 灵魂侧写 (CoT + 金牌话术) |
| **并发安全** | 无状态网关 | **AsyncAgentPool** (LRU 缓存 + 线程安全) |
| **数据源** | 仅静态知识库 | **死活数据解耦**：VectorRAG(静态) + MCP Tool Calling(动态) |
| **多租户** | 逻辑隔离 | **物理级隔离**：独立 Collection + 独立 MCP 路由 |

---

## 2. 核心接口契约 (API Gateway)

### 2.1 聊天接口 (升级版)
> **变更说明**：V2.0 新增 `expert_id` 请求字段，支持无状态多租户路由。

- **Endpoint**: `POST /api/v1/chat`
- **Request** (`ChatRequest`):
  ```json
  {
    "expert_id": "str (多租户路由键，必填)",
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
    "business_intent": "str (租户专属意图，如：病理问诊/技术排障)",
    "urgency_level": "str (高/中/低)",
    "retrieved_memories": "[{text, score(含rerank_score), citation_source, chunk_type}]",
    "mcp_results": "[{tool_name, result, response_time}] (新增：MCP 工具调用结果)",
    "prompt_length": 0,
    "generation_time": 0.0
  }
  ```

### 2.2 专家切换接口 (保留)
- **Endpoint**: `POST /api/v1/switch_expert`
- **Request**: `{"expert_id": "str"}`
- **Response**: `{"success": true, "message": "...", "expert_name": "..."}`

### 2.3 标题生成接口 (保留)
- **Endpoint**: `POST /api/v1/generate_title`
- **Request**: `{"user_query": "str"}`
- **Response**: `{"title": "str (不超过6字)"}`

### 2.4 健康检查 (升级版)
- **Endpoint**: `GET /health`
- **Response**:
  ```json
  {
    "status": "healthy",
    "active_experts": ["expert_id_1", "expert_id_2"],
    "pool_size": 3,
    "uptime_seconds": 3600
  }
  ```

### 2.5 文档上传接口 (新增)
- **Endpoint**: `POST /api/v1/ingest`
- **Request**: `multipart/form-data` (文件 + expert_id)
- **Response**:
  ```json
  {
    "success": true,
    "file_name": "技术手册.pdf",
    "file_hash": "md5_checksum",
    "chunks_count": 42,
    "parser_used": "DoclingParser"
  }
  ```

---

## 3. 模块规格说明书

### 模块一：多模态非结构化摄入中心 (Ingest Hub 2.0)

#### 3.1.1 统一解析引擎注册表 (Parser Registry)

**文件**: `services/ingest_hub.py` (新增)

```python
class DocumentParser(ABC):
    """解析器抽象基类"""
    @abstractmethod
    def parse(self, file_path: str) -> ParsedDocument: ...
    @abstractmethod
    def supported_extensions(self) -> List[str]: ...

class ParserRegistry:
    """解析器注册表 - 自动根据文件后缀分发"""
    _parsers: Dict[str, DocumentParser] = {}
    
    @classmethod
    def register(cls, parser: DocumentParser):
        for ext in parser.supported_extensions():
            cls._parsers[ext.lower()] = parser
    
    @classmethod
    def get_parser(cls, file_path: str) -> DocumentParser:
        ext = Path(file_path).suffix.lower()
        parser = cls._parsers.get(ext)
        if not parser:
            raise UnsupportedFormatError(f"不支持的文件格式: {ext}")
        return parser
```

**支持的格式矩阵**:

| 格式 | 解析器 | 引擎 | 输出 |
|------|--------|------|------|
| `.csv` | `SimpleTextParser` | 纯 Python (json.loads) | `{"speaker", "content"}` |
| `.jsonl` | `SimpleTextParser` | 纯 Python (逐行解析) | `{"speaker", "content"}` |
| `.pdf` | `DoclingParser` | Docling DocumentConverter | Markdown AST + 层级切片 |
| `.docx` | `DoclingParser` | Docling DocumentConverter | Markdown AST + 层级切片 |
| `.xlsx` | `DoclingParser` | Docling TableFormer | 表格 → Markdown 表格 |
| `.pptx` | `DoclingParser` | Docling SlideProcessor | 逐页 Markdown |

#### 3.1.2 层级自适应切片 (Hierarchical Chunking)

**废除 V1.0 的字符数硬截断**，改为 Docling 的 `HierarchicalChunker`：

```python
class HierarchicalChunker:
    """
    层级自适应切片器
    保持段落、标题、列表、表格的物理完整性
    自动向下传递层级元数据 (Metadata)
    """
    def chunk(self, doc: DoclingDocument) -> List[KnowledgeChunk]:
        """
        输入: DoclingDocument (层级 AST)
        输出: List[KnowledgeChunk] (带层级元数据)
        
        切片策略:
        - 按标题层级 (H1/H2/H3) 作为自然分割点
        - 表格整体保留，不跨页拆分
        - 列表项保持在同一 Chunk 内
        - 每个 Chunk 携带 parent_title, depth, page_number 元数据
        """
```

#### 3.1.3 解析沙箱隔离 (Sandbox Process)

```python
class SandboxedParser:
    """
    解析沙箱 - 子进程隔离执行
    防止 Docling 重度推理模型导致主进程内存坍塌
    """
    MAX_MEMORY_MB = 2048   # 2GB 内存上限
    TIMEOUT_SECONDS = 120  # 120 秒超时
    
    def parse_safe(self, file_path: str) -> ParsedDocument:
        """在独立子进程中执行解析"""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._do_parse, file_path)
            try:
                result = future.result(timeout=self.TIMEOUT_SECONDS)
                return result
            except TimeoutError:
                future.cancel()
                # 物理 kill 子进程
                import psutil
                for child in psutil.Process().children():
                    child.kill()
                raise ParseTimeoutError(f"解析超时 ({self.TIMEOUT_SECONDS}s): {file_path}")
```

#### 3.1.4 文件指纹去重 (MD5 Checksum)

```python
class FileFingerprint:
    """
    文件指纹库 - MD5 校验和去重
    避免相同文件被重复摄入 ChromaDB
    """
    FINGERPRINT_FILE = "data/.file_fingerprints.json"
    
    @classmethod
    def is_duplicate(cls, file_path: str) -> bool:
        md5 = cls._compute_md5(file_path)
        fingerprints = cls._load()
        if md5 in fingerprints:
            return True
        fingerprints[md5] = {"file_name": Path(file_path).name, "ingested_at": datetime.now().isoformat()}
        cls._save(fingerprints)
        return False
```

---

### 模块二：无状态并发网关与 Agent Pool

#### 3.2.1 AsyncAgentPool (异步缓冲池)

**文件**: `services/agent_pool.py` (新增)

```python
class AsyncAgentPool:
    """
    异步 Agent 缓冲池 - 无状态网关核心
    使用 LRU 淘汰算法缓存活跃专家实例
    最大缓存量默认 10 个
    
    [核心节点]：物理移除全局 agent 变量
    每个请求通过 expert_id 从池中获取独立实例
    """
    def __init__(self, max_size: int = 10):
        self._pool: Dict[str, ExpertDigitalTwinAgent] = {}
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._access_order: List[str] = []  # LRU 追踪
    
    async def get_or_create(self, expert_id: str) -> ExpertDigitalTwinAgent:
        """
        线程安全的 Agent 获取/创建
        双重检查锁 + LRU 淘汰
        """
        async with self._lock:
            # 1. 缓存命中
            if expert_id in self._pool:
                self._touch(expert_id)  # 更新 LRU
                return self._pool[expert_id]
            
            # 2. LRU 淘汰
            if len(self._pool) >= self._max_size:
                lru_key = self._access_order.pop(0)
                old_agent = self._pool.pop(lru_key)
                await self._cleanup_agent(old_agent)  # 关闭 MCP 连接等
            
            # 3. 创建新实例
            agent = await self._create_agent(expert_id)
            self._pool[expert_id] = agent
            self._access_order.append(expert_id)
            return agent
    
    async def prewarm(self):
        """
        异步预热 - 网关启动时扫描 data/experts/
        对有效专家进行基础配置预加载
        冷启动耗时控制在 100ms 以内
        """
        experts_dir = "data/experts/"
        expert_ids = [d for d in os.listdir(experts_dir) 
                     if os.path.isdir(os.path.join(experts_dir, d))]
        
        # 异步预加载 profile.json (不初始化 LLM 客户端)
        tasks = [self._preload_profile(eid) for eid in expert_ids[:self._max_size]]
        await asyncio.gather(*tasks)
```

#### 3.2.2 网关改造点

**文件**: `api_gateway.py` (修改)

| 改动点 | V1.0 (旧) | V2.0 (新) |
|--------|----------|----------|
| 全局变量 | `agent = ExpertDigitalTwinAgent(...)` | `pool = AsyncAgentPool(max_size=10)` |
| `/api/v1/chat` | `agent.generate_reply(...)` | `agent = await pool.get_or_create(request.expert_id)` |
| `/api/v1/switch_expert` | 全局变量重新赋值 | `pool.switch(expert_id)` 强制刷新 |
| 启动预热 | 无 | `await pool.prewarm()` |

---

### 模块三：多租户 MCP 动态挂载网关

#### 3.3.1 多租户 MCP 路由配置

**文件**: `data/experts/{expert_id}/profile.json` (扩展)

```json
{
  "expert_id": "jinpaifuwu_001",
  "expert_name": "金牌架构师",
  "domain_expertise": "云计算架构设计与故障排查",
  "mcp_endpoints": {
    "enabled": true,
    "timeout_seconds": 15,
    "tools": [
      {
        "name": "query_incident_db",
        "description": "查询故障工单系统",
        "server_url": "http://internal-erp:8080/mcp/incidents",
        "allowed_params": ["incident_id", "severity"],
        "rate_limit": 10
      },
      {
        "name": "lookup_knowledge_base",
        "description": "查询内部知识库",
        "server_url": "http://internal-wiki:9090/mcp/search",
        "allowed_params": ["keyword", "category"]
      }
    ]
  },
  "business_redlines": [...]
}
```

#### 3.3.2 MCP 客户端生命周期管理

**文件**: `services/mcp_client.py` (新增)

```python
class MCPClientManager:
    """
    MCP 客户端管理器
    每个专家实例拥有独立的 MCP 客户端连接
    专家实例被淘汰时同步关闭长连接
    """
    def __init__(self, expert_id: str, mcp_config: Dict):
        self.expert_id = expert_id
        self.config = mcp_config
        self._clients: Dict[str, MCPClient] = {}
    
    async def initialize(self):
        """异步初始化所有 MCP 客户端连接"""
        for tool in self.config.get("tools", []):
            client = MCPClient(
                server_url=tool["server_url"],
                tool_name=tool["name"],
                allowed_params=tool.get("allowed_params", []),
                rate_limit=tool.get("rate_limit", 10)
            )
            await client.connect()
            self._clients[tool["name"]] = client
    
    async def execute_tool(self, tool_name: str, params: Dict) -> Dict:
        """执行 MCP 工具调用"""
        client = self._clients.get(tool_name)
        if not client:
            raise MCPToolNotFoundError(f"工具 {tool_name} 未配置")
        return await client.call(params)
    
    async def shutdown(self):
        """物理关闭所有 MCP 长连接"""
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()
```

#### 3.3.3 双轨混合推理 (Hybrid Reasoning)

**文件**: `services/agent_engine.py` (修改)

在 `generate_reply()` 中新增 MCP 调用节点：

```
[步骤 1] 业务意图分诊
    ↓
[步骤 2] 记忆召回 (RAG) ──────────────────────────────┐
    ↓                                                   │
[步骤 2.5] MCP 工具调用 (新增) ←── 并发执行 ────────────┤
    ↓                                                   │
[步骤 3] Prompt 组装 (RAG 结果 + MCP 结果 融合) ←──────┘
    ↓
[步骤 4] LLM 生成
```

```python
# [核心节点]：MCP 双轨混合推理
mcp_results = {}
if hasattr(self, 'mcp_manager') and self.mcp_manager:
    # 检测是否需要动态数据查询
    if probe_state.business_intent in self.mcp_manager.get_supported_intents():
        print(f"[MCP 双轨推理] 检测到动态数据查询意图，并发调用 MCP 工具")
        for tool_name in self.mcp_manager.list_tools():
            try:
                result = await self.mcp_manager.execute_tool(
                    tool_name, 
                    {"query": user_input}
                )
                mcp_results[tool_name] = result
            except Exception as e:
                print(f"[MCP 降级] 工具 {tool_name} 调用失败: {e}")
                # MCP 失败不阻塞主链路，降级为纯 RAG
```

---

### 模块四：数字灵魂蒸馏 2.0 (Cognitive Mirroring)

#### 3.4.1 专家思维树提取 (Thought-Tree Extraction)

**文件**: `services/etl_pipeline.py` (升级)

V1.0 的 `LLMMapNode` 仅提取简单的 QA_PAIR/SOP_STEP/BUSINESS_RULE。V2.0 升级为带分支决策的 CoT Pattern：

```python
class CoTPatternExtractor:
    """
    专家决策思维链提取器
    从对话中提取带有分支决策的思维树
    
    输出格式:
    {
        "trigger_condition": "客户提到'服务器502'",
        "decision_tree": [
            {
                "step": "第一步：确认故障现象",
                "branch": {
                    "if_502": "检查 Nginx 日志",
                    "if_connection_refused": "检查后端服务端口"
                }
            },
            {
                "step": "第二步：定位根因",
                "branch": {
                    "if_upstream_timeout": "检查后端响应时间",
                    "if_bad_gateway": "检查上游代理配置"
                }
            }
        ]
    }
    """
```

#### 3.4.2 金牌话术库动态语气校准

```python
class ToneCalibrationMatrix:
    """
    语气校准矩阵
    提取专家最常用的 10 个金牌句式
    在 Prompt Suturing 阶段建立语气校准
    
    校准维度:
    - 句式长度分布 (短句率 vs 长句率)
    - 语气词使用频率 (啊/吧/呢/哦)
    - 专业术语密度
    - 反问句比例
    """
    def extract_patterns(self, golden_few_shots: List[Dict]) -> Dict:
        """从金牌示例中提取语气特征向量"""
        patterns = {
            "avg_sentence_length": self._calc_avg_length(golden_few_shots),
            "tone_word_freq": self._calc_tone_word_freq(golden_few_shots),
            "question_ratio": self._calc_question_ratio(golden_few_shots),
            "top_10_phrases": self._extract_top_phrases(golden_few_shots, n=10)
        }
        return patterns
```

---

## 4. 物理级安全与稳健性防线 (Hardlines)

### 4.1 ChromaDB 集合硬隔离 (保留 V1.0)
- **规则**: 每个 expert 拥有完全独立的 Collection `expert_{clean_id}_memory`
- **检查点**: 所有检索操作必须带 `where={"expert_id": expert_id}` 过滤
- **违规后果**: 重大安全故障，立即物理拉闸

### 4.2 Windows I/O 稳健性 (保留 V1.0)
- **规则**: 日志写入与会话存储必须通过 `try-except-retry` 机制保护
- **新增**: 引入 `asyncio.Queue` 异步写入队列，彻底解决 WinError 32

### 4.3 Token 费用熔断 (升级)
- **规则**: 单次 ETL 摄入数据流超过 50 万 Token 时自动拉闸
- **新增**: 在 `SemanticChunker` 中增加 Token 计数器，使用 `tiktoken` 精确估算

### 4.4 解析沙箱熔断 (新增)
- **规则**: Docling 解析必须在独立子进程中执行
- **限制**: 单次解析最大内存 2GB，超时 120 秒
- **违规后果**: 物理 `kill` 子进程，返回降级错误

### 4.5 MCP 调用熔断 (新增)
- **规则**: 单次 MCP 调用超时 15 秒
- **限制**: 每个工具每分钟最多调用 10 次 (rate_limit)
- **违规后果**: MCP 失败不阻塞主链路，降级为纯 RAG 回复

### 4.6 文件指纹去重 (新增)
- **规则**: 相同 MD5 的文件禁止重复摄入
- **存储**: `data/.file_fingerprints.json`
- **违规后果**: 返回 "文件已存在" 错误，不执行任何写入

---

## 5. 数据存储结构 (V2.0)

```
data/
├── .file_fingerprints.json        # 文件指纹库 (MD5 去重) [新增]
├── chroma_db/                      # ChromaDB 持久化向量数据库
│   └── (ChromaDB 内部文件)
├── experts/                        # 多租户专家池 (物理隔离)
│   └── {expert_id}/
│       ├── profile.json            # 专家画像 (含 MCP 配置) [扩展]
│       ├── knowledge.json          # 知识库 (KnowledgeChunk[])
│       ├── bm25_index.pkl          # BM25 关键词索引
│       └── tone_matrix.json        # 语气校准矩阵 [新增]
├── raw/                            # 原始数据
│   ├── source_data.csv             # 原始脏数据 (ShareGPT 格式)
│   └── uploaded/                   # 上传文档暂存区 [新增]
│       └── {file_hash}.pdf
├── staging/
│   └── demo_staging.jsonl          # 暂存格式
└── sessions/                       # 会话历史
    └── {expert_id}/
        └── {session_id}.json       # 单次会话数据
logs/
├── system_trace.log                # 系统追踪日志 (JSONL)
└── ingest_errors.log               # 文档解析错误日志 [新增]
```

---

## 6. 技术栈 (V2.0 扩展)

| 组件 | V1.0 | V2.0 新增 | 用途 |
|------|------|-----------|------|
| 文档解析 | 无 | **Docling** | PDF/Word/Excel/PPTX 版面解析 |
| 并发框架 | 无 | **asyncio** | 异步 Agent Pool |
| MCP 协议 | 无 | **MCP Python SDK** | 动态工具调用 |
| 进程管理 | 无 | **multiprocessing** | 解析沙箱隔离 |
| 文件指纹 | 无 | **hashlib (MD5)** | 文件去重 |
| Token 计数 | 无 | **tiktoken** | Token 熔断精确估算 |
| 系统监控 | 无 | **psutil** | 子进程内存/CPU 监控 |

---

## 7. 版本演进路线图

```
V1.0 (已完成) ──────────────────────────────────────────────────
  ✅ 专家灵魂克隆 (双轨制 ETL)
  ✅ 混合检索引擎 (Dense + Sparse + Reranking)
  ✅ 多租户物理隔离 (ChromaDB 集合级)
  ✅ 业务意图路由 + 算力风控
  ✅ 神经缝合 Prompt (金牌话术 + CoT + 反机器味)

V2.0 (当前版本) ────────────────────────────────────────────────
  ✅ 多模态非结构化摄入中心 (Ingest Hub 2.0)
     ├── Parser Registry (统一解析引擎注册表)
     ├── Docling 版面解析 (PDF/Word/Excel/PPTX)
     ├── 层级自适应切片 (Hierarchical Chunking)
     ├── 解析沙箱隔离 (Sandbox Process)
     └── 文件指纹去重 (MD5 Checksum)
  
  ✅ 无状态并发网关与 Agent Pool
     ├── AsyncAgentPool (双重检查锁 + asyncio.to_thread)
     ├── 异步生命周期预热 (Pre-warming)
     └── 物理移除全局 agent 变量
  
  ✅ 契约 ACL 闭环
     ├── ChatRequest expert_id 选参 (100% 向下兼容)
     └── switch_expert 无状态化 (agent_pool.reload_agent)
  
  ✅ BM25 内存常驻缓存
     ├── HybridSearchEngine 内部自动降级
     └── 不依赖外部 memory_manager

V3.0 (进行中) ────────────────────────────────────────────────
  🔲 多租户 MCP 动态挂载网关
     ├── profile.json MCP 路由配置
     ├── MCP 客户端生命周期管理
     └── 双轨混合推理 (RAG + MCP 融合)
  
  🔲 数字灵魂蒸馏 2.0
     ├── 专家思维树提取 (CoT Pattern)
     ├── 金牌话术库动态语气校准
     └── Token 熔断升级 (tiktoken 精确估算)
  
  🔲 SQL 会话存储 (PostgreSQL/Redis)

V4.0 (远期规划) ────────────────────────────────────────────────
  🔲 MCP 动态 ERP API 挂载 (实时数据查询)
  🔲 Orchestrator 编排网关 (多 Agent 协作)
  🔲 生产级监控告警体系 (Grafana/Prometheus)
  🔲 A/B 测试框架 (Prompt 效果对比)
```


---

## 8. 附录：V1.0 → V2.0 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **新增** | `services/ingest_hub.py` | 多模态摄入中心 (Parser Registry + Docling + 沙箱) |
| **新增** | `services/agent_pool.py` | AsyncAgentPool 异步缓冲池 |
| **新增** | `services/mcp_client.py` | MCP 客户端管理器 |
| **修改** | `api_gateway.py` | 移除全局 agent，接入 AsyncAgentPool |
| **修改** | `services/agent_engine.py` | 注入 MCP 双轨混合推理节点 |
| **修改** | `services/etl_pipeline.py` | 升级 CoT Pattern 提取 + 语气校准矩阵 |
| **修改** | `domain/models.py` | 新增 MCP 配置相关模型 |
| **修改** | `requirements.txt` | 新增 docling, tiktoken, psutil 等依赖 |
| **保留** | `services/vector_db_service.py` | 混合检索引擎不变 |
| **保留** | `services/state_tracker.py` | 意图探针不变 |
| **保留** | `services/expert_manager.py` | 专家管理器不变 |
| **保留** | `domain/models.py` | 核心数据契约不变 (仅扩展) |
