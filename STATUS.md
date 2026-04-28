# Kaiwu v3 项目状态记录

> 项目路径：D:\program\codeagent2604\kaiwu
> 启动日期：2026-04-26
> 目标：本地模型 coding agent，通过确定性专家流水线让本地模型达到最高任务完成率

---

## 当前状态：v0.7.0 UI全面优化 (PASS)

v0.6.2全部功能 + UI四件事：
1. 删掉所有机器内部信息（logger只写文件，warnings静默，--verbose才显示终端）
2. 执行过程改成spinner动画（rich.progress SpinnerColumn，transient=True完成后消失）
3. 完成后输出用户友好结果摘要（修改文件+改动bullet+测试结果，失败显示原因）
4. Header简化（三行纯文字替代像素大字）+ 状态栏深色背景（bg:#1a1a1a）
测试：282/282全绿（265回归+17 E2E）。
测试：207/207全绿（174回归+33 P1新测试）。

---

## v0.4 新增模块

### 专家注册表 (kaiwu/registry/)
- 12 个预置专家 YAML（api, bugfix, deepseekapi, docstring, fastapi, mybatis, refactor, springboot, sqlopt, testgen, typehint, uniapp）
- ExpertRegistry: 内存+磁盘双层，关键词饱和匹配（1命中=0.50, 2=0.75, 3=0.875）
- ExpertLoader: YAML 加载 + 校验
- ExpertPackager: .kwx 导入/导出（ZIP 格式）
- 生命周期状态机：new → mature → declining → archived

### 3 层记忆系统 (kaiwu/memory/)
- PROJECT.md — 项目级记忆（技术栈、架构、约定）
- EXPERT.md — 专家级记忆（每个专家的经验积累）
- PATTERN.md — 模式级记忆（跨项目的通用模式）

### 专家飞轮 (kaiwu/flywheel/)
- TrajectoryCollector — 任务执行轨迹记录（~/.kaiwu/trajectories/）
- PatternDetector — 重复成功模式检测（gate 1: >=5次同类型+同流水线+全成功）
- ExpertGeneratorFlywheel — LLM 从轨迹生成专家 YAML 草稿
- ABTester — 三门验证（gate 2 回测 + gate 3 AB 测试）
- LifecycleManager — 专家生命周期状态机

### 专家打包 (.kwx)
- `kaiwu expert export <name>` → 导出 .kwx 文件
- `kaiwu expert install <path.kwx>` → 安装到 ~/.kaiwu/experts/

### KaiwuMCP Router (kaiwu/mcp/)
- router_mcp.py — MCP 协议路由器
- `kaiwu serve-mcp` 启动 MCP 服务

### CLI 子命令
- `kaiwu expert list/info/export/install/remove/create`
- `kaiwu status` — 查看项目状态
- `kaiwu serve-mcp` — 启动 MCP 服务

---

## 验证结果

| 验证项 | 结果 | 备注 |
|--------|------|------|
| V1 Gate JSON稳定性 | 100% 解析成功率，67% 类型准确率 | gemma3:4b，不需要 grammar 约束 |
| V2 OpenHands集成 | 跳过，走 FLEX-1 自实现 | ToolExecutor 5个工具已完成 |
| V3 Locator精度 | 文件级 90%，函数级 20% | 函数级已加 few-shot 优化，待更大模型验证 |
| V4 搜索模块 | 意图4/4, DDG 4/4, Fetch 3/4, 压缩4/4 | trafilatura+bs4, 耗时略超15s(LLM瓶颈) |
| V5 AST Locator | A组(LLM)文件100%/函数50%, B组(AST)100%/100% | +50pp提升，值得集成 |
| V6 专家生成质量 | gemma3:4b 1/3, gemma4:e2b 3/3 PASS | 小模型JSON生成弱，大模型全过 |
| E2E 单文件 | 通过 | gemma3:4b 5.7s / gemma4:e2b 64.9s，5/5 测试 |
| E2E 多文件 | 通过 | gemma3:4b 7.7s，password leak 跨2文件，3/3 测试 |
| gemma4:e2b Gate | 100% 类型准确率（含 office） | 比 gemma3:4b 的 67% 大幅提升，但慢 10x |
| Office Expert | Excel 5.4KB / PPT 31KB / DOCX 37KB 全部通过 | deepseek-r1:8b，路径A(LLM生成脚本→执行) |
| Prompt Optimizer | dry-run 24任务框架跑通 | 源文件是stub/buggy，全FAIL是预期 |
| 重试三策略 | 3种prompt表述验证不同 + reflection注入 | strategy 0/1/2 + pattern_md失败记录 |
| V11 BM25+图Locator | 349节点/460边, BM25 4/5命中, <5ms | SQLite持久化+增量更新, rank-bm25 |

---

## 搜索模块架构（2026-04-26 追加）

```
SearchAugmentorExpert.search(ctx)
  ① IntentClassifier    — 纯关键词，毫秒级，github/arxiv/pypi/bug/general
  ② QueryGenerator      — 一次LLM调用，2-3条英文query
  ③ DuckDuckGoSearcher  — bs4解析HTML，零API key
  ④ QualityFilter       — 域名黑白名单，最多3个URL
  ⑤ ContentFetcher      — trafilatura(降级httpx)，每页≤800字
  ⑥ ContextCompressor   — 一次LLM调用，≤400字摘要
```

---

## 架构

```
用户输入（CLI）
    │
    ▼
  ExpertRegistry.match()  ← 关键词匹配，毫秒级
    │ 命中 → 注入 expert.system_prompt
    │ 未命中 → 走 Gate
    ▼
  Gate（单次LLM调用，结构化JSON路由）
    │
    ▼ 按 expert_type 选择流水线
  ┌─────────────────────────────────┐
  │ locator_repair: Locator→Generator→Verifier │
  │ codegen:        Generator→Verifier          │
  │ refactor:       Locator→Generator→Verifier  │
  │ doc:            Generator                    │
  │ office:         OfficeHandler (LLM生成脚本→执行) │
  └─────────────────────────────────┘
    │
    ▼ 失败重试（最多3次，三策略切换：normal→error-first→minimal）
  第1次失败后reflection分析根因 → 第2次失败触发搜索增强
  SearchAugmentor → 重新跑流水线
    │
    ▼
  TrajectoryCollector 记录轨迹
    │
    ▼
  3层记忆写入 (PROJECT.md / EXPERT.md / PATTERN.md)
    │
    ▼ 后台飞轮
  PatternDetector → ExpertGenerator → ABTester → LifecycleManager
```

## 文件结构

```
kaiwu/
├── pyproject.toml
└── kaiwu/
    ├── cli/main.py              # CLI入口 typer+rich (expert/status/serve-mcp/checkpoint子命令)
    ├── core/
    │   ├── context.py           # TaskContext 数据类 (+doc_context, kwcode_rules)
    │   ├── gate.py              # Gate 分类器
    │   ├── orchestrator.py      # 流水线编排器 (+checkpoint+kwcode_md注入+降级建议)
    │   ├── planner.py           # /plan计划模式+风险评估(P1新增)
    │   ├── checkpoint.py        # 文件快照(git stash/文件复制)(P1新增)
    │   └── kwcode_md.py         # KWCODE.md加载+分段注入(P1新增)
    ├── experts/
    │   ├── locator.py           # BM25+图主路径(零LLM) → LLM兜底 (+DocReader注入)
    │   ├── generator.py         # 从文件读original，LLM只生成modified (+doc_context)
    │   ├── verifier.py          # 语法检查 + pytest 验证
    │   ├── search_augmentor.py  # 6步搜索流水线编排
    │   └── office_handler.py    # Office文档生成(LLM生成脚本→执行)
    ├── knowledge/
    │   └── doc_reader.py        # 非代码文件读取(PDF/Word/MD/TXT+BM25Plus)(P1新增)
    ├── registry/
    │   ├── expert_registry.py   # 内存+磁盘双层注册表，关键词饱和匹配
    │   ├── expert_loader.py     # YAML加载+校验(VALID_PIPELINE_STEPS含office/chat)
    │   └── expert_packager.py   # .kwx导入/导出 (ZIP格式)
    ├── builtin_experts/         # 15个预置专家YAML(含3个office专家)
    │   ├── api.yaml
    │   ├── bugfix.yaml
    │   ├── fastapi.yaml
    │   ├── testgen.yaml
    │   ├── office_docx.yaml
    │   ├── office_xlsx.yaml
    │   ├── office_pptx.yaml
    │   └── ... (15个)
    ├── flywheel/
    │   ├── trajectory_collector.py  # 轨迹记录 → ~/.kaiwu/trajectories/
    │   ├── pattern_detector.py      # gate 1: 重复模式检测
    │   ├── expert_generator.py      # LLM生成专家YAML草稿
    │   ├── ab_tester.py             # gate 2+3: 回测+AB测试
    │   └── lifecycle_manager.py     # 专家生命周期状态机
    ├── memory/
    │   ├── project_md.py        # PROJECT.md 项目级记忆
    │   ├── expert_md.py         # EXPERT.md 专家级记忆
    │   ├── pattern_md.py        # PATTERN.md 模式级记忆 (+count_similar_failures)
    │   └── kaiwu_md.py          # KAIWU.md 兼容旧版
    ├── mcp/
    │   └── router_mcp.py        # KaiwuMCP Router
    ├── search/
    │   ├── intent_classifier.py # 纯关键词意图分类
    │   ├── query_generator.py   # LLM生成英文query
    │   ├── duckduckgo.py        # DDG HTML scraper (bs4)
    │   ├── quality_filter.py    # 域名黑白名单
    │   ├── content_fetcher.py   # trafilatura/httpx正文提取
    │   └── context_compressor.py# LLM压缩摘要
    ├── llm/llama_backend.py     # llama.cpp + Ollama 双后端 (timeout=360s)
    ├── ast_engine/
    │   ├── parser.py            # TreeSitterParser (Python only MVP)
    │   ├── call_graph.py        # CallGraph (内存dict实现)
    │   ├── locator.py           # ASTLocator (关键词→图展开)
    │   ├── graph_builder.py     # GraphBuilder (SQLite全量/增量构建)
    │   └── graph_retriever.py   # GraphRetriever (BM25+图遍历检索)
    ├── tools/
    │   ├── executor.py          # read/write/bash/list/git 工具层
    │   └── ast_utils.py         # AST符号提取
    ├── tests/test_core.py       # 38个单元测试
    ├── tests/bench_tasks/       # 24个Python bench任务(从cl-v2迁移)
    │   ├── bench_tasks.json     # 任务索引
    │   ├── t01_pipeline/        # stub: 实现数据处理pipeline
    │   ├── t04_hidden_bug_calc/ # buggy: 修复计算器bug
    │   └── ... (24个)
    ├── scripts/
    │   └── prompt_optimizer.py  # bench测试+Opus API分析+自动优化循环
    ├── changelogs/              # optimizer自动记录
    └── validation/              # V1-V11 验证脚本 + 结论JSON
        ├── v1_gate_stability.py
        ├── v2_openhands_check.py
        ├── v3_locator_accuracy.py
        ├── v4_search_module.py
        ├── v5_ast_locator.py
        ├── v6_expert_generation.py
        └── v11_graph_locator.py
```

---

## 踩坑记录（经验教训）

### 1. Reasoning 模型的 stop 参数会截断 thinking

**现象**：deepseek-r1:8b 通过 Ollama 调用时，content 始终为空。
**根因**：Gate 传了 `stop=["\n\n"]`，reasoning 模型的 `<think>` 块内有空行，stop 在 thinking 阶段就触发了截断，content 还没生成就结束了。
**修复**：对 reasoning 模型不传 stop 参数。
**教训**：reasoning 模型的 thinking tokens 是"隐形"的，所有影响生成终止的参数（stop、max_tokens）都要考虑 thinking 的开销。

### 2. Ollama 对 temperature=0 的请求有 KV cache

**现象**：修复代码后重跑测试，deepseek-r1 仍然返回空。
**根因**：之前 temperature=0 的空结果被 Ollama 缓存了，后续相同 prompt 直接返回缓存。
**修复**：reasoning 模型 temperature=0 改为 0.01；测试前 `POST /api/generate {"model": "xxx", "keep_alive": 0}` 卸载模型清缓存。
**教训**：Ollama 的缓存机制对调试有干扰，遇到"代码改了但结果不变"时先怀疑缓存。

### 3. Generator 的 original 不能让 LLM 生成

**现象**：Generator 让 LLM 同时输出 original 和 modified，但 LLM 输出的 original 经常省略注释行或空行，导致 apply_patch 精确匹配失败。
**根因**：小模型复述代码时会"改写"而不是精确复制。
**修复**：original 从文件直接读取（`_extract_function` 按缩进提取完整函数），LLM 只生成 modified。
**教训**：凡是需要精确匹配的内容，绝对不要让 LLM 生成。LLM 负责创造，代码负责精确。

### 4. Verifier 的 pytest 命令要指定 tests/ 目录

**现象**：patch apply 成功，但 Verifier 报 `ModuleNotFoundError`。
**根因**：`pytest --tb=short -q` 没指定目录，pytest 从 cwd 递归收集，可能收集到上层目录的测试文件导致 import 冲突。
**修复**：改为 `python -m pytest tests/ --tb=short -q`。
**教训**：subprocess 跑测试时，路径隔离很重要。

### 5. 不要在 apply_patch 里做 fuzzy match

**尝试**：为了兼容 LLM 输出的不精确 original，在 apply_patch 里加了行级 fuzzy match 和 LLM merge fallback。
**结果**：增加了复杂度但没解决根因，fuzzy match 的边界条件很多。
**正确做法**：从源头解决——original 从文件读取，保证 100% 精确匹配。apply_patch 只做 exact match。
**教训**：下游打补丁不如上游修根因。

### 6. deepseek-r1:8b 的 /api/generate 完全不可用

**现象**：`/api/generate` 返回空 response，`done_reason: length`。
**根因**：thinking tokens 消耗了全部 `num_predict` 配额，content 没有预算。`/api/chat` 会把 thinking 和 content 分开计算。
**修复**：Ollama 后端统一走 `/api/chat`，不用 `/api/generate`。
**教训**：reasoning 模型必须用 chat API。

### 7. gemma3:4b 的 office 类分类准确率低

**现象**：V1 验证中 office 类 20 条只有 4 条正确，大部分被分为 codegen。
**根因**：4B 模型对"Excel/Word/PPT"这类关键词的语义理解不够，倾向于把"生成"类任务都归为 codegen。
**影响**：不影响 MVP（office 是 stub），但换更大模型后需要重新验证。
**教训**：Gate 的分类准确率直接依赖模型能力，小模型适合粗粒度分类（3-4 类），细粒度需要更大模型。

### 8. trafilatura.fetch_url 没有超时控制

**现象**：V4 验证每个 case 耗时 30-120s，远超 15s 红线。
**根因**：`trafilatura.fetch_url(url)` 内部用 urllib，默认无超时，遇到慢站点会阻塞很久。
**修复**：不用 `trafilatura.fetch_url`，改为 `httpx.get(url, timeout=5.0)` 自己下载 HTML，再传给 `trafilatura.extract()` 做正文提取。
**教训**：第三方库的网络请求一定要自己控制超时，不要信任库的默认值。

### 9. StackOverflow 403 拒绝爬虫

**现象**：V4 验证 bug 类 case fetch 全部失败。
**根因**：StackOverflow 对非浏览器 User-Agent 返回 403。
**影响**：MVP 可接受（snippet 兜底），后续可加 cloudscraper 或更真实的 UA。
**教训**：高质量源不一定能爬到，QualityFilter 的白名单排序不等于能 fetch 成功。

---

## 下一步计划

- [x] git init + 首次提交
- [x] 搜索模块 6 步流水线
- [x] CLI 交互式 REPL（/model /cd /plan /help 等命令）
- [x] 函数级定位优化（AST 提取候选 → LLM 选择，单函数文件跳过 LLM）
- [x] StackOverflow 403 修复（StackExchange API）
- [x] 符号索引辅助文件定位（跨文件 bug 修复验证通过）
- [x] 多文件修改 E2E（password leak 跨 models.py+service.py，3/3 测试通过）
- [x] codegen 流水线验证（纯生成通过，但写到 new_code.py 而非目标文件）
- [x] 拉更大模型验证（gemma4:e2b Gate 100%准确率，E2E通过）
- [x] Windows 兼容性（GBK编码修复）
- [x] Gate codegen/locator_repair 边界优化（prompt 明确描述，5/5 边界 case 通过）
- [x] 性能优化：reasoning模型think=false，gemma4 64.9s→19.3s（3.4x提速）
- [x] 非Python语言支持（JS/Go/Rust regex提取验证通过）
- [x] 专家注册表（12个预置专家，关键词匹配，生命周期状态机）
- [x] 3层记忆系统（PROJECT.md / EXPERT.md / PATTERN.md）
- [x] 专家飞轮（轨迹收集 → 模式检测 → 专家生成 → 三门验证 → 生命周期）
- [x] 专家打包（.kwx 导入/导出）
- [x] KaiwuMCP Router
- [x] CLI 子命令（expert list/info/export/install/remove/create, status, serve-mcp）
- [x] V5/V6 验证脚本框架（就绪，需要Ollama在线运行）
- [x] 安装脚本（install.ps1 + install.sh，国内镜像适配）
- [x] 中文文档（README_zh.md）
- [x] E2E 端到端验收（fibonacci off-by-one，gemma3:4b，22.4s，4/4测试，含重试+搜索+记忆+轨迹）
- [x] Windows cmd原生验证（Python import + pytest 24/24 通过）
- [x] 红线约束代码review（10/10 CORE 全部 PASS）
- [x] V5 AST Locator验证（A组函数50% vs B组100%，+50pp，AST值得集成）
- [x] V6 专家生成质量验证（gemma4:e2b 3/3 PASS，gemma3:4b 1/3）
- [x] 预置专家抽样验证（BugFix 5/5=100%, TestGen gemma4 3/5=60%）
- [x] CLI补全（--no-search, memory --reset）
- [x] 中国网络优化（DDG→Bing fallback, httpx代理, ModelScope自动切换, 安装脚本网络探测）
- [x] CLI命令改名 kaiwu → kwcode（包名不变，入口+显示名+MCP工具名全部更新）
- [x] 飞轮端到端验证（5次任务→模式检测→专家生成→Gate2通过→注册→lifecycle new→mature→declining）
- [x] Gate 2 真实回测修复（submit_candidate 现在用orchestrator重跑source_trajectories，对比成功率）
- [x] Gate 3 AB测试集成（orchestrator.run()自动交替候选/基线，record_ab_result，10次后auto-graduation）
- [x] AB测试仿真脚本（validation/ab_tester_simulation.py，真实LLM调用验证三道门）
- [x] FastAPIExpert路由冲突修复（加fastapi接口/fastapi路由/starlette等中文关键词，降低min_confidence到0.5）
- [x] Context Pruner（纯算法，头尾保留+中间关键词提取，67%压缩率，<10ms）
- [x] StatusBar + TokPerSecEstimator（4档自适应宽度，EMA平滑tok/s）
- [x] SysInfo + VRAMWatcher（psutil RAM + nvidia-smi GPU，后台10s刷新）
- [x] CLI界面升级（Header渲染 + StatusBar集成 + Pruner集成 + LLM计时）
- [x] V7 Context Pruner验证（67%压缩率，8.9ms/22K tokens，关键词保留）
- [x] V8 StatusBar渲染验证（4档宽度全部PASS）
- [x] crawl4ai完全移除（BOOT-RED-3），content_fetcher.py改为trafilatura唯一主路径
- [x] 首次启动引导（onboarding.py：欢迎→网络探测→API配置→连通性验证→保存→进入REPL）
- [x] network.py更新（KWCODE_PROXY环境变量 + ~/.kwcode/config.yaml优先读取）
- [x] pyproject.toml更新（name=kwcode, v0.4.1, 加networkx/pytest/aiosqlite依赖）
- [x] LLMBackend.set_endpoint()动态切换API endpoint
- [x] /api命令（show/temp/default，REPL内切换API配置）
- [x] main.py集成onboarding首次引导 + config.yaml默认值读取
- [x] Gate降级策略改为chat（不再降级到locator_repair）
- [x] ChatExpert实现（非编码问题先搜索再回复，纯问候直接回复）
- [x] Gate prompt加chat类型描述+few-shot示例（gemma4分类准确率提升）
- [x] reasoning模型前缀匹配（qwen3-vl/qwen3-coder自动覆盖）
- [x] thinking字段提取（qwen3-vl content为空时从thinking字段读取）
- [x] /model持久化到~/.kwcode/config.yaml
- [x] CLI界面v2：像素大字KW-CODE + meta strip + prompt_toolkit bottom_toolbar常驻状态栏
- [x] /命令补全（prompt_toolkit Completer，输入/弹出菜单）
- [x] 产品名kwqode→kwcode全量替换（16文件68处）
- [x] SearXNG统一搜索替换DDG/Bing特殊处理（install.sh/ps1自动部署Docker）
- [x] content_fetcher简化（去掉StackOverflow特殊处理，SearXNG已覆盖）
- [x] search_augmentor简化（snippet优先，去掉intent_classifier/query_generator依赖）
- [x] chat模式隐藏Gate分析信息（只显示"思考中..."）
- [x] SSL verify=False修复fetch反爬失败
- [x] 搜索query清洗（去问候语/指令词前缀）
- [x] codegen文件名提取（从用户输入正则提取目标文件名，写到project_root真实路径，CLI显示"✓ 已生成：完整路径"）
- [x] 专家工具能力声明（12个YAML + Generator/ChatExpert prompt全部加tool capability，修复模型"没有权限"问题）
- [x] SearXNG自动启动（kwcode启动时检测Docker容器，自动start/run，CLI显示启动状态）
- [x] ChatExpert搜索降级优化（搜索失败不再瞎编"无法访问"，改用专门降级prompt诚实告知）
- [x] codegen多语言文件名（_detect_extension从用户输入推断.html/.js/.sh等，不再全部fallback到.py）
- [x] Generator防工具调用输出（NEWFILE_PROMPT加target_file+禁止输出命令，_clean_code_output过滤write_file等行）
- [x] SearXNG JSON格式自动配置（_ensure_json_format检测并启用json格式，避免403）
- [x] Docker镜像源配置（daemon.json加docker.1ms.run/docker.xuanyuan.me，国内可拉镜像）
- [x] 搜索链路重写：snippet+fetch → LLM提取关键信息（EXTRACT_PROMPT），不再直接喂噪音给模型
- [x] codegen实时数据预搜索（_needs_realtime_data检测天气/股价/新闻等关键词，首次就触发搜索）
- [x] Locator升级：BM25+SQLite调用图（graph_builder.py+graph_retriever.py，主路径零LLM调用，LLM降级兜底）
- [x] V11验证：349节点/460边/1.4s构建，BM25检索4/5命中，单次<5ms，增量更新+持久化全PASS
- [x] Orchestrator集成notify_task_result（任务完成后更新图统计+增量更新被修改文件）
- [x] Bug修复：CLI stdout wrapper安全检查（IDE/pipe环境不崩）
- [x] Bug修复：onboarding API验证区分401/403认证错误（不再把auth失败当成功）
- [x] Bug修复：ExpertRegistry threshold clamp到1.0（防止penalty溢出导致专家永远不触发）
- [x] Bug修复：Generator Class.method匹配（_func_in_file/_extract_function支持AST的"Class.method"格式）

### 待做

1. ~~backup/restore CLI 命令（spec §10.3）~~ ✅ checkpoint list/restore 已实现
2. SQLite 跨 session 查询（spec §7.1 kaiwu.db）
3. 12 个预置专家完整 benchmark（目前只跑了 BugFix+TestGen）
4. ~~E2E 30任务验收（需Ollama在线，QA_SPEC_V2 §9）~~ ✅ 26/30通过(87%)
5. ~~P1 E2E验收~~ ✅ 8/8通过（KWCODE.md注入+/plan风险评估+checkpoint还原+DocReader注入）
6. ~~P2 E2E验收~~ ✅ 6/6通过（模型自适应+飞轮通知+ValueTracker统计）
7. ~~集成E2E~~ ✅ 3/3通过（Gate分类+Chat流水线+Codegen流水线，真实gemma3:4b）

### v0.4.3 QA修复清单（2026-04-27）

| # | Bug | 修复文件 | 修复内容 |
|---|-----|---------|---------|
| B-1 | chat搜索失败→建议去网站查 | chat_expert.py | CHAT_SEARCH_FAIL_SYSTEM重写：禁止列URL/编造 |
| B-2 | codegen编造实时数据 | generator.py | NEWFILE_PROMPT加防编造规则5/6 |
| B-3 | codegen搜索失败无防护 | generator.py | _run_codegen注入防编造警告 |
| B-4 | think标签污染生成代码 | generator.py | _clean_code_output加re.sub清理 |
| B-5 | apply_patch空original损坏文件 | executor.py | 空original提前return False |
| B-6 | 短输入被当问候语 | chat_expert.py | 去掉len<=3判断 |
| B-7 | Ollama无message字段崩溃 | llama_backend.py | .get("message",{})防护 |
| B-8 | graph结果缺字段KeyError | locator.py | 过滤缺少file_path/name的结果 |
| B-9 | Gate._parse对null崩溃 | gate.py | except加AttributeError/TypeError |
| B-10 | CHAT_SEARCH_SYSTEM未强制使用数据 | chat_expert.py | 加"严格基于搜索结果" |
| B-11 | codegen覆盖已有文件 | generator.py | 文件存在时加数字后缀 |
| B-12 | verifier误判无测试 | verifier.py | list_dir错误结果过滤 |
| B-15 | config损坏启动崩溃 | onboarding.py | .get()防护 |
| B-16 | test_gen None in f-string | generator.py | or 'source'防护 |
| B-17 | SQLite并发锁崩溃 | graph_builder.py | timeout=10.0 |
| B-18 | gate_result缺key崩溃 | cli/main.py | .get()防护 |
| B-19 | orchestrator异常未捕获 | cli/main.py | try/except |
| B-20 | MCP malformed arguments | router_mcp.py | isinstance+str()防护 |
| B-21 | .kwx非UTF-8崩溃 | expert_packager.py | try/except UnicodeDecodeError |

### v0.4.3 Gate叠加模式重构 + E2E验收（2026-04-27）

**架构改动：**
- Gate从"专家替代模式"改为"叠加模式"：LLM通用分类为主，专家system_prompt作为领域知识叠加
- 专家匹配结果不再覆盖expert_type，而是通过route_type区分：general / general_with_expert / expert_registry
- doc流水线加Locator：["generator"] → ["locator", "generator"]

**专家trigger_keywords清理（去泛词）：**
- APIExpert：去掉"接口/路由/route/请求"，保留api/endpoint/rest/restful/swagger/openapi
- BugFixExpert：min_confidence 0.85→0.95（防抢通用locator_repair）
- DocstringExpert：去掉"文档/说明/描述"，保留docstring/注释/comment/代码注释/函数注释
- RefactorExpert：去掉"简化/优化代码/clean"，保留重构/refactor/去重/deduplicate/代码重构
- OfficeDocxExpert：去掉"word/文档"（word匹配get_last_word），改为word文档/word模板/.docx
- FastAPIExpert：去掉"异步接口/async api"
- TypeHintExpert：去掉"注解/typing"（注解和Spring冲突），保留类型注解/type hint/mypy

**E2E 30题验收（gemma4:e2b）：26/30通过(87%)**
- 第一组（代码修复+生成）：8/10
- 第二组（Chat+搜索+边界）：9/10
- 第三组（复杂+跨文件+极端）：9/10
- 4个失败全是模型能力限制（T3添加函数/T9测试目录/T16 docstring/T21跨文件hash），非框架问题

### v0.4.4~v0.4.5 cl-v2规范蒸馏 + Office Expert + 重试策略重构（2026-04-27~28）

**管道修通 + 规则注入**
- expert_system_prompt管道修通：generator/locator/chat_expert三个专家的llm.generate()全部接入system=参数
- quality_rules_minimal + china_env注入：15个builtin expert YAML的system_prompt前缀加了5条质量规则+中文环境编码/镜像规则
- GENERATOR_BASE_SYSTEM：model_behavior.md适配版(517chars)，反过度工程/反幻觉/反过度验证
- TestGenExpert升级：system_prompt从4行→1556chars完整测试规范(AAA模式/Mock策略/边界覆盖)
- WEB_DESIGN_RULES注入：从cl-v2 web.md提炼(1113chars)，web任务自动追加到Generator system

**Office Expert实现（路径A: LLM生成脚本→执行）**
- office_handler.py从stub改为完整实现：检测类型→选scene prompt→LLM生成Python脚本→语法预检+auto_fix→run_bash执行→检查文件
- 三套scene prompt：XLSX(openpyxl样式模板)、PPTX(python-pptx API约束)、DOCX(完整模板代码方式)
- 三个office YAML：office_docx/xlsx/pptx.yaml，trigger_min_confidence=0.4
- expert_loader VALID_PIPELINE_STEPS加office/chat，gate _PIPELINE_TO_TYPE加映射
- 验证结果：Excel 5.4KB首次成功，PPT 31KB加API约束后成功，DOCX 37KB改用模板方式后成功

**Prompt Optimizer + Bench框架**
- 24个Python bench任务从cl-v2迁移到kaiwu/tests/bench_tasks/
- bench_tasks.json任务索引(task_id/dir_name/description/files/test_file/test_cmd)
- prompt_optimizer.py：bench跑测试→Opus API分析失败→自动修改expert YAML→对比通过率→保留或回滚
- dry-run验证通过，24任务框架跑通

**重试三策略（替换原有同prompt重试）**
- TaskContext新增字段：retry_strategy(0/1/2)、previous_failure、reflection
- orchestrator重试逻辑：每次重试递增retry_strategy，三次用完全不同的prompt表述
- Generator._build_retry_prompt：strategy 0=正常需求描述，1=从错误出发，2=最小化修改
- _do_reflection：第一次失败后LLM一句话分析根因(≤50字)，注入后续重试prompt
- pattern_md失败记录：update()记录error_detail到recent_failures列表，PATTERN.md新增"近期失败模式"section

**代码审计清理**
- 去除冗余getattr（4个文件改为直接属性访问）
- _build_retry_prompt空search_ctx不再产生多余空行
- LLM timeout 180s→360s（PPT/DOCX代码量大）
- max_tokens 3000→4096（office脚本）

### v0.5.0 P1四大功能（2026-04-28）

**任务一：KWCODE.md项目规则文件**
- core/kwcode_md.py — load_kwcode_md()按[section]标签分段解析，build_kwcode_system()按expert_type注入
- 加载优先级：项目根目录KWCODE.md → ~/.kwcode/KWCODE.md（全局规则）
- P1-RED-1：token上限4800字符（~1200 tokens，15%的8K窗口），超限截断
- generate_kwcode_template()：自动检测测试框架(pytest/npm/go/cargo)，生成模板
- orchestrator集成：TaskContext创建后注入kwcode_rules到expert_system_prompt前缀
- /init命令同时生成KWCODE.md和KAIWU.md

**任务二：/plan计划模式+风险评估**
- core/planner.py — Planner类+PlanStep数据类+estimate_risk()三档评估
- 风险评级规则：历史失败记录(权重最高) > 任务复杂度(文件数/函数数/跨模块) > 描述清晰度
- P1-RED-5：只用High/Medium/Low三档，不输出百分比
- P1-RED-2：/plan模式下未确认不修改任何文件
- _preview_locator()：只读预览BM25+图检索结果，不调LLM
- pattern_md.count_similar_failures()：关键词匹配历史失败记录
- CLI集成：/plan <任务> 直接执行 或 /plan 后输入任务；--plan CLI参数

**任务三：Checkpoint文件快照**
- core/checkpoint.py — git stash主路径 + 文件复制兜底(~/.kwcode/checkpoints/)
- P1-RED-3：快照失败必须告知用户，不能静默失败
- P1-FLEX-1：非git仓库用manifest.json记录原始路径，精确还原
- orchestrator集成：流水线执行前save()，成功后discard()，失败后restore()+降级建议
- _suggest_downgrade()：多文件失败建议缩小到单函数，hard任务建议拆分
- CLI子命令：kwcode checkpoint list / kwcode checkpoint restore

**任务四：非代码文件读取**
- knowledge/doc_reader.py — PDF(pdfplumber)/Word(python-docx)/MD/TXT/RST读取
- BM25Plus段落匹配（BM25Okapi在少文档场景IDF为0，改用BM25Plus）
- P1-RED-4：读取失败降级跳过，不中断主流程
- P1-FLEX-2：扫描件PDF（提取为空）静默跳过
- locator.py集成：_inject_doc_context()在两条路径(graph/llm)都注入
- generator.py集成：doc_context追加到prompt末尾"相关文档参考"section
- token预算：max_tokens=800（context的10%）

**测试**
- test_p1_features.py：33个新测试（KWCODE.md 11 + Planner 5 + Checkpoint 6 + DocReader 5 + PatternMd 3 + Context 1 + 全局fallback 2）
- 全量回归：207/207 PASS（174旧 + 33新）

**版本升级**
- pyproject.toml version 0.4.2→0.5.0
- cli/main.py VERSION 0.4.3→0.5.0
- TaskContext新增字段：doc_context, kwcode_rules

### v0.6.0 P2三大功能（2026-04-28）

**任务一：模型能力自适应**
- core/model_capability.py — ModelTier(SMALL/MEDIUM/LARGE) + STRATEGIES策略表 + detect_model_tier()
- 检测优先级：Ollama API参数量 → 模型名正则(:8b/:14b/:72b) → 已知列表 → 默认MEDIUM
- P2-RED-1：检测全部本地完成，不发数据出网
- SMALL策略：force_plan_mode=True, max_files=2, search_trigger_after=1, gate_confidence=0.90
- LARGE策略：force_plan_mode=False, max_files=8, search_trigger_after=2, gate_confidence=0.70
- CLI集成：启动时显示模型模式（小模型模式/大模型模式），REPL任务执行自动应用策略
- _tier_cache缓存避免重复检测

**任务二：飞轮可见性通知**
- notification/flywheel_notifier.py — FlywheelNotifier + FlywheelNotification数据类
- 三种通知：expert_born(Rich Panel) / progress(3/5进度) / milestone(50/100/200/500任务)
- P2-RED-2：通知不打断当前任务，缓存到~/.kwcode/pending_notifications.json，REPL循环开始时flush
- ab_tester.py集成：check_graduation()通过后自动queue_expert_born（含成功率/速度对比数据）
- REPL集成：while True循环顶部notifier.flush(console)

**任务三：价值量化仪表盘**
- stats/value_tracker.py — SQLite本地统计(~/.kwcode/stats.db)
- P2-RED-3：数据只存本地，不上传任何服务器
- P2-RED-4：时间估算保守5min/task，不夸大
- record()：每次任务完成后记录(project/expert_type/expert_name/success/elapsed/retry/model)
- get_summary()：过去N天统计(总任务/成功数/节省时间/最活跃专家)
- kwcode stats命令：Rich格式价值报告
- P2-FLEX-3：<5个任务时不显示统计，避免无意义数字
- 启动周报：_maybe_show_weekly_stats()每7天显示一次本周统计
- orchestrator集成：_record_value()成功/失败都记录，_check_milestone()里程碑检测

**测试**
- test_p2_features.py：21个新测试（ModelCapability 11 + FlywheelNotifier 5 + ValueTracker 5）
- 全量回归：228/228 PASS（174旧 + 33 P1 + 21 P2）

**版本升级**
- pyproject.toml + cli/main.py VERSION → 0.6.0

### v0.6.1 搜索模块重构（2026-04-28）

**四级内容提取管道**
- search/extraction_pipeline.py — 借鉴 local-deep-research 的多级提取架构
- Level 1: trafilatura（统计+规则启发式，多语言，markdown输出）
- Level 2: newspaper3k（新闻/论坛页面强，与Level 1并行跑）
- 质量评分选胜者：_quality_score() = len(text) - boilerplate_count * 500
- Level 3: readabilipy（Mozilla Readability DOM级提取，fallback）
- Level 4: BeautifulSoup get_text（去script/style/nav/footer，last resort）
- 中文 boilerplate 关键词支持（登录/注册/隐私政策/用户协议）

**并行搜索引擎**
- duckduckgo.py 重构：SearXNG + DDG 用 ThreadPoolExecutor(max_workers=2) 并行执行
- _search_parallel()：结果按URL去重合并，即时回答(无URL)始终保留
- 两引擎都可用时并行提高召回率+速度；单引擎可用时自动降级

**ContentFetcher简化**
- content_fetcher.py 从97行缩减到18行，薄封装调用 extraction_pipeline.fetch_and_extract()
- 接口不变（fetch/fetch_many），下游 search_augmentor.py 无需改动

**测试**
- test_search_refactor.py：19个新测试（ExtractionPipeline 8 + ContentFetcher 4 + ParallelSearch 4 + EdgeCases 3）
- 回归测试适配：TestFetchTimeout 改为检查 extraction_pipeline（旧方法已删除）
- 全量回归：246/246 PASS（227旧 + 19新）

**版本升级**
- pyproject.toml + cli/main.py VERSION → 0.6.1

**可选依赖（提升提取质量，非必须）**
- newspaper3k / newspaper4k — Level 2 提取（未安装时跳过）
- readabilipy — Level 3 提取（未安装时跳过）
- 已有依赖：trafilatura, beautifulsoup4（Level 1+4 始终可用）

### v0.6.2 意图感知搜索 + ChatExpert搜索门控（2026-04-28）

**意图分类器增强**
- intent_classifier.py 重写：5类意图(code_search/academic/package/debug/general)
- 关键词大幅扩充：code_search加"最优解/设计模式/源码"，academic加"SOTA/benchmark"，debug加"crash/segfault"
- 新增 LLM fallback：关键词未命中时调本地模型分类（可选，传入llm参数启用）
- 向后兼容：旧意图名(github/arxiv/pypi/bug)在query_generator里保留映射

**ChatExpert搜索门控（修复无脑搜索）**
- chat_expert.py 新增 _needs_search() 方法，替代原来的无条件搜索
- 优先级：实时数据关键词(今天/天气/价格) → 始终搜索（最高优先级）
- Follow-up检测：短句(<20字)+追问词(穿什么/为什么/详细) → 不搜索
- 纯推理/建议类：建议/合适/对比/区别 → 不搜索（模型自己推理）
- 解决的问题：问了天气后追问"穿什么"不再触发无意义搜索

**QueryGenerator方向提示增强**
- _DIRECTION_MAP 新增 code_search/academic/package/debug 四个详细方向提示
- code_search：引导生成含 implementation/source code/github 的 query
- academic：引导生成含 paper/algorithm/arxiv/survey 的 query
- 旧映射保留向后兼容

**测试**
- test_intent_search.py：19个新测试（IntentClassifier 11 + ChatExpertGating 5 + QueryGenerator 3）
- 全量回归：265/265 PASS（246旧 + 19新）

**版本升级**
- pyproject.toml + cli/main.py VERSION → 0.6.2

**BM25Plus结果重排**
- search_augmentor.py 新增 _rerank_results() 静态方法
- 搜索结果回来后，用用户原始问题对 title+snippet 做 BM25Plus 重打分
- 最相关的结果排前面，无关博客/导航页自然下沉
- 零额外依赖（复用已有 rank_bm25）
- 搜索量从 max_results=8 提升到 10（多取再排，取 Top-8）

**Bugfix: Checkpoint Windows路径崩溃**
- checkpoint.py: save()先验证project_root存在，_file_copy()的mkdir和rglob加OSError防护
- codegen新建文件场景（空目录无文件可备份）不再报错，直接标记saved=True

**Bugfix: 小模型plan确认太啰嗦**
- cli/main.py: codegen/easy、chat、office跳过plan确认（低风险不需要用户确认）
- 只有locator_repair、refactor、codegen/hard才显示计划等确认

**Bugfix: DocReader中文分词**
- doc_reader.py: 新增 _tokenize() 函数，CJK字符逐字拆分+英文单词保持完整
- 解决中文query（如"JWT登录认证"）无法匹配中文文档的问题（BM25按空格分词对中文无效）

**P1+P2 E2E验收（2026-04-28，gemma3:4b真实模型）**
- test_e2e_p1p2.py：17个E2E测试，全部用真实Ollama模型跑
- P1验收结果：
  - KWCODE.md加载+注入 ✓
  - /plan生成3步计划+风险等级 ✓
  - 历史失败→风险上升 ✓
  - Checkpoint save/restore ✓
  - Checkpoint codegen空目录不崩 ✓
  - DocReader MD文档读取+BM25匹配 ✓
  - DocReader PDF降级不崩 ✓
- P2验收结果：
  - gemma3:4b → ModelTier.SMALL ✓
  - SMALL策略：force_plan=True, max_files=2 ✓
  - 飞轮通知入队+flush显示 ✓
  - 里程碑通知 ✓
  - ValueTracker record+get_summary ✓
  - 保守时间估算(5min/task) ✓
- 集成验收结果：
  - Gate分类："你好"→chat, "写排序函数"→codegen ✓
  - Chat流水线：真实LLM回复 ✓
  - Codegen流水线：生成patch+验证通过(2.9s) ✓
  - ValueTracker自动记录 ✓
- 全量测试：282/282 PASS

### v0.7.0 UI全面优化（2026-04-28）

**删掉所有机器内部信息**
- 入口处 warnings.filterwarnings("ignore") 静默所有 RuntimeWarning
- kaiwu logger 只写文件(~/.kwcode/kwcode.log)，propagate=False 不输出到终端
- --verbose 参数时才 propagate=True 显示到终端
- 删除的输出：codegen|easy|xxx、Generator->Verifier、生成patch、语法OK|测试0/0、Gate解析降级、expert_name(route)conf=xxx

**执行过程改成spinner动画**
- rich.progress SpinnerColumn + TextColumn，transient=True 完成后自动消失
- Gate阶段："分析任务..."，Locator："定位代码..."，Generator："生成修改..."，Verifier："验证结果..."
- 搜索触发时："搜索增强中..."，反思时："分析失败原因..."
- _spinner_callback 更新 spinner description，verbose 模式同时输出旧式文字

**完成后输出用户友好结果摘要**
- 成功：✓ 完成 (Xs) + 修改了 xxx.py + bullet point 改动描述 + 测试通过(N/N)
- codegen成功：✓ 已生成 /full/path/file.html (Xs) + bullet point 功能描述
- 失败：✗ 失败 (Xs) + 原因（前3行错误）

**Header简化 + 状态栏深色**
- 删掉像素大字Logo(_GLYPHS/_render_pixel_title/_render_meta_strip/_render_expert_panel全删)
- 改为三行纯文字：KWCode 天工开物 vX.X.X / 分隔线 / model · project · N专家
- 状态栏背景从 bg:ansiblack 改为 bg:#1a1a1a fg:#666666（深灰，不再有白块）

**版本升级**
- pyproject.toml + cli/main.py VERSION → 0.7.0

**kwcode setup-search 一键安装**
- cli/main.py 新增 `kwcode setup-search` 命令
- 4步流程：检查Docker → 检查容器 → 拉镜像(searxng/searxng ~200MB) → 启动容器
- 自动启用JSON格式（sed修改settings.yml + 重启容器）
- 容器名：kwcode-searxng，端口8080，restart=always
- 安装完成后显示管理命令（stop/start/rm）
- 无Docker时给出各平台安装链接
- 用户体验：`pip install kwcode && kwcode` 直接能用(DDG)，想要更好搜索跑一次 `kwcode setup-search`
