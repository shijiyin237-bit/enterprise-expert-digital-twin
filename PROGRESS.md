# ⏱️ 项目进度与状态机

> **防断层终极武器** — 每次重构前后必须更新此文件。
> 记录已完成基线与当前正在执行的任务，确保指挥官在任何时刻都能掌握项目全貌。

---

## 🟢 当前稳定基线：V2.0 (多模态与并发无状态中台版)


> Git Tag: (待提交) — `feat: release v2.0-core with concurrent stateless AsyncAgentPool, in-memory BM25 RAG, and layout-aware multimodal IngestHub`


### ✅ 已完成的核心里程碑

#### 1. 强契约数据漏斗 (Data Contract)
- [x] `tools/sharegpt_to_jsonl.py` — 纯物理拆解 CSV(ShareGPT) → `{"speaker", "content"}` 暂存格式，零 LLM 依赖
- [x] `data/staging/demo_staging.jsonl` — 内置 400 行高质量真实语料作为演示数据
- [x] `start_system.py` 自动嗅探 staging 文件，物理旁路旧版 UniversalIngestor

#### 2. 双轨制 ETL 炼油厂 (Dual-Track ETL)
- [x] `services/etl_pipeline.py` — Map-Reduce 架构，并发调用 LLM 提取知识
- [x] **知识压缩轨**: `SemanticChunker` 语义切片 → `LLMMapNode` 提取 QA_PAIR/SOP_STEP/BUSINESS_RULE → `LLMJudgeReduce` 模糊去重(阈值0.85) + 分批压缩(40条/批)
- [x] **灵魂侧写轨**: `DigitalTwinDistiller` 逆向推导专家语气、红线、CoT 思维链、金牌话术
- [x] **物理剥壳机**: `_clean_and_parse_json()` 正则提取 JSON，无视 LLM 废话包装
- [x] **自省纠错**: JSON 解析失败时自动发起第二次 LLM 修复请求
- [x] **Token 熔断**: `MAX_CORPUS_SIZE=500` 硬编码防线，超大数据集强制截断

#### 3. 多租户物理隔离 (Multi-Tenancy)
- [x] `services/expert_manager.py` — `ExpertManager` 单例，管理 `data/experts/{expert_id}/` 物理隔离目录
- [x] `services/vector_db_service.py` — ChromaDB 集合级隔离 `expert_{id}_memory`，查询时 `where={"expert_id": ...}` 过滤
- [x] `api_gateway.py` — `POST /api/v1/switch_expert` 运行时热切换专家，无需重启
- [x] `web_ui.py` — 前端专家档案室 + 多租户热切换闭环（前端切换 → 网关同步 → 清空会话）

#### 4. 混合检索引擎 (Hybrid RAG)
- [x] `services/vector_db_service.py` — `HybridSearchEngine` 三路召回架构
- [x] **Dense Retrieval**: ChromaDB + BAAI/bge-m3 向量召回 Top-20
- [x] **Sparse Retrieval**: BM25Okapi + jieba 中文分词关键词召回 Top-20
- [x] **Cross-Encoder Reranking**: BAAI/bge-reranker-v2-m3 精细排序
- [x] **降级链**: 重排失败 → 原始顺序 | 混合检索无结果 → 纯向量 | 向量失败 → 本地 BM25 内存索引检索 (HybridSearchEngine 内部自动降级，不依赖外部 memory_manager)


#### 5. 业务意图路由 (Intent Routing)
- [x] `services/state_tracker.py` — `BusinessIntentProbe` 动态意图探针
- [x] 基于专家画像 `supported_intents` 的租户专属意图识别
- [x] **算力风控**: 兜底意图物理阻断向量检索，跳过 RAG
- [x] **兜底降级**: 非法意图强制降级为 `supported_intents[-1]`

#### 6. 推理生成引擎 (Generation)
- [x] `services/agent_engine.py` — `ExpertDigitalTwinAgent.generate_reply()` 完整生成链路
- [x] **神经缝合 Prompt**: 专家身份 + 沟通风格 + 金牌话术 + 话术使用护栏(80%概率锁) + 业务红线 + CoT 思维链 + 知识切片 + RAG 降噪护栏 + Golden Few-Shots + 终极反机器味红线
- [x] **富文本遥测**: `retrieved_memories` 包含 rerank_score、citation_source、chunk_type 等硬核指标

#### 7. 基础设施与可观测性
- [x] `api_gateway.py` — FastAPI 网关 (端口 8088)，Pydantic 请求/响应契约
- [x] `web_ui.py` — Streamlit 前端 (端口 8501)，B 端业务沙盘 + CTO 全息观测站
- [x] `start_system.py` — 一键点火中枢，编排 Ingestion → 启动后端 → 启动前端 → 打开浏览器
- [x] **系统追踪日志**: `logs/system_trace.log` JSONL 格式，记录每次请求的全生命周期
- [x] **CTO 观测站**: 数据流向图、意图分诊指标、RAG 全息遥测、推理耗时监控图表
- [x] **Windows I/O 护栏**: `write_system_trace()` try-except 防 WinError 32 并发死锁
- [x] **反 LLM 谄媚**: `domain/models.py` `clean_llm_fluff()` 正则清洗 10 种废话模式
- [x] **防破产机制**: ETL 阶段必须手动触发，绝不自动执行高成本流程
- [x] **GitHub 零泄露**: `.gitignore` + `.env.example` 配置模板

---

## 🟡 当前正在执行：V3.0 演进筹备 (MCP 摄入网关与技能工厂版)

### 目标 1：架构文档体系建立 (已完成)
- [x] `ARCHITECTURE.md` — 系统架构与防线图纸 (V2.0) ✅ 已完成

- [x] `PROGRESS.md` — 进度与状态机 (本文件) ✅ 已完成
- [x] `PRD.md` — 产品需求文档 (V2.0 完整规格) ✅ 已完成

### 目标 2：多模态非结构化摄入中心 (Ingest Hub 2.0) 🔄 进行中
- [x] **实现 Parser Registry**：`services/etl_pipeline.py` — `BaseDocumentParser` 抽象基类 + `ParsedDocument` 数据契约，自动根据文件后缀分发 A/B 轨
- [x] **实现 CSVLegacyParser**：继承 `BaseDocumentParser`，重构原 `SemanticChunker.load_and_chunk` 逻辑，输出统一 `ParsedDocument` 契约
- [x] **实现 Docling 版面解析**：PDF/Word/Excel/PPTX → Markdown AST + `HierarchicalChunker` 层级切片
- [x] **实现导入防爆机制**：`_lazy_init()` 懒加载 Docling，防止 Torch 内存坍塌
- [x] **实现物理沙箱隔离**：`ProcessPoolExecutor(max_workers=1)` 独立子进程，120 秒超时物理 kill
- [x] **实现文件指纹去重**：`BaseDocumentParser.compute_file_hash()` MD5 校验和
- [x] **实现 A/B 双轨分级分发**：`run_map_reduce_etl()` 根据文件后缀自动判定 A 轨（CSV/JSONL → 画像侧写流水线）或 B 轨（PDF/DOCX/XLSX → 直接落盘 + 向量化）
- [x] **实现 B 轨跳过对话提纯**：静态客观知识不走 Map-Reduce 和画像侧写，直接落盘至 `tenant_{tenant_id}_kb` 集合


### 目标 3：无状态并发网关与 Agent Pool ✅ 已完成
- [x] **实现 AsyncAgentPool**：`api_gateway.py` 内联注入 — `AsyncAgentPool` 类，双重检查锁 + `asyncio.to_thread` 剥离重度 I/O
- [x] **改造 api_gateway.py**：物理移除全局 `agent` 变量，接入 `agent_pool = AsyncAgentPool()`，`/api/v1/chat` 动态解析 `request.expert_id` 多租户分流
- [x] **实现异步预热**：`@app.on_event("startup")` 异步生命周期钩子，网关启动时预载默认专家，首个请求 0ms 延迟
- [x] **ChatRequest 强契约升级**：新增 `expert_id: Optional[str] = Field(default=None)` 选参，100% 向下兼容老版前端
- [x] **switch_expert 无状态化**：彻底去除 `global agent` 危险变量，通过 `agent_pool.reload_agent()` 刷新缓存池


### 目标 4：多租户 MCP 动态挂载网关
- [ ] **实现 MCP 客户端管理器**：`services/mcp_client.py` — 生命周期管理
- [ ] **扩展 profile.json**：新增 mcp_endpoints 配置段
- [ ] **实现双轨混合推理**：在 agent_engine.py 中注入 MCP 调用节点

### 目标 5：数字灵魂蒸馏 2.0
- [ ] **实现专家思维树提取**：CoT Pattern 升级为带分支决策的思维树
- [ ] **实现金牌话术库动态语气校准**：ToneCalibrationMatrix
- [ ] **Token 熔断升级**：引入 tiktoken 精确估算


---

## 🔴 待解决的已知问题 (Bugs / Technical Debts)

### 阻断性 Bug
- [ ] 暂无阻断性 Bug。V1.0 核心链路已验证通过。

### 技术债 (Technical Debts)

| 优先级 | 类别 | 问题描述 | 影响范围 | 计划解决版本 |
|--------|------|---------|---------|-------------|
| 🟡 中 | **ETL 成本** | ETL 流程重度依赖 LLM (Qwen2.5-72B)，Token 消耗较高，小规模语料(<100行)性价比低 | 启动门槛高，不适合快速原型验证 | V3.0 |
| 🟢 低 | **前端体验** | Streamlit 前端在 CTO 观测站的 Prompt 内容展示仅为长度统计，未实现完整 Prompt 可视化 | 调试体验受限 | V3.0 |
| 🟢 低 | **会话管理** | 会话数据以 JSON 文件存储，未接入数据库，大规模会话场景下检索效率低 | 仅影响历史会话较多的场景 | V3.0 |
| 🟢 低 | **监控告警** | 系统追踪日志仅本地文件存储，未对接外部监控大盘 (如 Grafana) | 生产部署可观测性不足 | V3.0 |


---

## 📋 版本演进路线图

```
V1.0 (已完成) ──────────────────────────────────────────────────────────────
  ✅ 专家灵魂克隆 (双轨制 ETL)
  ✅ 混合检索引擎 (Dense + Sparse + Reranking)
  ✅ 多租户物理隔离 (ChromaDB 集合级)
  ✅ 业务意图路由 + 算力风控
  ✅ 神经缝合 Prompt (金牌话术 + CoT + 反机器味)

V2.0 (当前版本) ────────────────────────────────────────────────────────────
  ✅ Ingest Hub 2.0 Docling AST (Parser Registry + A/B 双轨分发)
  ✅ AsyncAgentPool 异步无状态池 (双重检查锁 + asyncio.to_thread)
  ✅ BM25 内存常驻缓存 (HybridSearchEngine 内部自动降级)
  ✅ 契约 ACL 闭环 (ChatRequest expert_id 选参 + 100% 向下兼容)
  ✅ CTO 遥测完全体 (富文本 retrieved_memories + 推理耗时监控)

V3.0 (进行中) ────────────────────────────────────────────────────────────
  🔲 MCP 多租户文档解析网关 (MCP 客户端管理器 + 双轨混合推理)
  🔲 专家即标准 Skill 导出 (profile.json MCP 路由配置)
  🔲 SQL 会话存储 (PostgreSQL/Redis)
  🔲 自适应缝合 (ToneCalibrationMatrix 动态语气校准)

V4.0 (远期规划) ──────────────────────────────────────────────────────────
  🔲 MCP 动态 ERP API 挂载 (实时数据查询)
  🔲 Orchestrator 编排网关 (多 Agent 协作)
  🔲 生产级监控告警体系 (Grafana/Prometheus)
  🔲 A/B 测试框架 (Prompt 效果对比)
```


---

## 🔧 快速状态速查

| 维度 | 状态 | 说明 |
|------|------|------|
| **核心链路** | 🟢 稳定 | 数据摄入 → ETL → 意图路由 → 混合检索 → 生成，全链路已验证 |
| **多租户** | 🟢 稳定 | 物理隔离 + 热切换闭环 |
| **可观测性** | 🟢 基础 | 系统追踪日志 + CTO 观测站 |
| **数据摄入** | 🟡 受限 | 仅支持 CSV(ShareGPT) 格式 |
| **生产部署** | 🟡 待完善 | 缺数据库、监控告警、并发锁 |
| **文档体系** | 🟢 完成 | ARCHITECTURE.md + PROGRESS.md + README.md + engineering_norms.md |
