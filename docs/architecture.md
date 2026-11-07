# coRoof V1 Architecture

当前实施边界：V1 阶段 1–8 的本地业务、标准接口与持续关注实现（2026-11-04）。模块化单体；Next.js 与 FastAPI 同源代理，API 和 Worker 共享 Python 领域代码，PostgreSQL 保存业务事实，Redis 只负责队列。真实外部联调、实际身份/投递服务和团队试点尚未验收；原有 Go 模块单独保留。

```text
Browser (Owner / Manager / Member)
  -> Next.js /api proxy
  -> FastAPI identity + membership scope + typed command
  -> PostgreSQL transaction: WorkItem projection + WorkEvent + audit

Raw text -> UpdateProvider (RulesProvider)
  -> validated UpdateDraft + AnalysisRun
  -> explicit author confirmation + version check
  -> same transactional work/event path

Authorized WorkItem + WorkEvent -> rules -> Signal + immutable EvidenceSnapshot
  -> bounded, authorized context -> structured model adapter / explicit rules fallback
  -> AnalysisRun -> Owner prepares Decision -> explicit confirmation + freshness check
  -> append DecisionOutcome + WorkEvent + audit (no automatic work-state change)

Celery + Redis + Beat -> bounded connector jobs + transactional outbox
```

API 层不依赖组件，DTO 由 OpenAPI 生成。组织和角色在服务器读取；数据表使用租户复合外键。任何 AI/连接器都只能在相同事实与授权边界接入。详情见 [领域模型](domain-model.md)、[API](api-contract.md)、[ADR](adr/0001-stack.md) 与 [后续扩展](extensions.md)。

空库只通过 Alembic 迁移建结构，不自动填入虚构数据。首次登录后由用户建立企业。默认 mock 身份与规则草稿只用于本地开发，production 模式失败关闭。Compose 以独立 migrate 进程先迁移，再启动 API/Worker。

当前页面以“动态全景 → 需要你处理 → 项目进展 → 折叠的处理记录与团队动态”为企业概览顺序，同事项提醒合并，项目明细按需展开。工作查询保留一个底部输入，在非模态居中浮层先给结论与下一步；证据、其他方案和处理过程默认折叠。全局详情复用居中原生对话框，查看资料与业务确认才打开。老板先核对已准备的安排，可展开修改后一次明确确认；确认事务与角色权限不因操作简化而减少。决策经验和本人 AI 偏好从个人设置进入。

## Agent 与模型框架（2026-11-04 更新）

按用户最新要求，V1 Agent 以老板需求定义业务能力，不接入 Skills。LLM 只提出结构化能力请求；Harness 和服务端执行器验证当前身份、租户、对象权限、参数、确认状态及运行额度，再映射到固定工具和领域服务。业务写入继续经过明确确认、版本校验、幂等和审计。

读取 Agent 的首批四项工作能力支持有界查询、取消、失权拒绝、持久化步骤和显式恢复，后续知识与经验能力沿用同一授权入口。现按用户要求迁移到 LangChain 模型集成与 LangGraph 执行图；官方 checkpoint 存储通过 Alembic 建立，租户与运行使用复合外键绑定。业务事务、明确确认、预算与审计保持 coRoof 领域服务所有。框架不自动执行任意工具、不从图状态授予权限。

2026-11-05 的 [Yuxi 对照改进](yuxi-improvements.md) 将明确交互查询改为持久提交：`POST /agent/runs/submit` 在同一事务保存 AgentRun 与 AgentExecution，Celery/Beat 负责投递和有租约的单步执行。浏览器用 GET 观察，`GET /agent/runs/active` 找回当前仍获授权的任务；刷新与历史读取不推进模型步骤。Worker 复用现有读取图、幂等键及企业额度，取消、原会话失效、撤权或来源变化会阻止后续执行，未知模型调用不自动重放。0018 迁移不回填旧任务。一次明确只读请求的执行意图不增加业务权限，也不授予持续关注；后者仍由独立 WatchGrant 的目标、范围、期限与额度约束。

前台读取支持显式父查询引用：最多读取直接父轮及其两层祖先，每层都必须是同租户、本人、原有效会话中的已完成只读任务，创建未满 24 小时且当前权限、工作及知识版本仍有效。序列化后的整个上下文最多 1,800 字节；各层只取自己的有限问题与摘要，来源提示优先直接父轮，不递归复制它们已经保存的上下文。旧答复不是当前事实，新轮次重新授权读取。后台关注和草稿任务不能携带父查询，任一纳入层失效时不静默丢弃上下文并重试。当前提示为 `agent-read-v10`；技术约束见 [读取循环](agent-read-loop.md)。

ModelGateway 作为薄的任务与策略边界，内部委托 LangChain；不再维护各家 HTTP 请求/响应协议。Coding Plan 真实合成验收仅用于开发测试，通用 MaaS 验收按用户修订顺序移至发布前。能力目录见 [Agent 设计](agent-capabilities.md)，当前实现和边界见 [模型层](model-layer.md) 与 [读取循环](agent-read-loop.md)。

2026-11-05 用户明确授权增加单连接本机流程测试例外：已有凭据经运维指定源与目标、按目标企业独立加密导入，保存不等于测试或启用。部署侧允许名单默认空，本轮只列入一个目标连接；仅开发/测试环境、mock 身份、回环 `web_origin` 与精确 Profile 匹配时，显式连接测试和前台 Agent 可使用，后台持续关注仍拒绝。未列入名单、非本机和生产环境保持关闭，生产预检拒绝非空开发名单。该测试配置不改变角色、业务确认、租户预算和加密隔离，也不等同于供应商用途许可或正式应用验收。详见 [AI 管理边界](ai-management.md#本轮单连接本机测试例外)。

阶段 3 使用 LangGraph interrupt/Command 等待作者确认，节点复用现有 UpdateDraft / Decision 命令与事件事务。图状态不能授予业务权限；提交前重读当前身份、事项与版本。PostgreSQL 会话 advisory lock 串行化同一确认图，业务提交后才保存图完成状态；中断后明确重试依赖领域命令幂等返回原结果。见 [Agent 提案](agent-actions.md)。

已确认安排可由事项当前获授权成员读取，反馈复用 UpdateDraft，经本人确认后在同一事务追加关联安排的 WorkEvent、更新投影并审计，不自动改变事项状态或生成结果结论；租户复合外键与迁移边界见 [领域模型](domain-model.md)。

2026-11-04 的授权增补将模型接入扩展到四种协议：OpenAI Responses、Anthropic Messages、Gemini generateContent、Chat Completions。业务输出仍经原契约严格校验；Claude 不支持的长度约束移入字段说明及完整 Schema 提示，本地校验保留。企业配置模块独立管理加密 BYOK、平台服务、用量与审计；统一网关仍不持有数据库 Session。配置变更通过短事务更新，调用前校验当前配置版本与租户额度。详见 [企业 AI 管理](ai-management.md)。

## 企业知识库

阶段 5 的 [企业知识库](knowledge.md) 复用现有读取图，提供 `knowledge.search` 原文检索与 `knowledge.list` 已发布目录。明确目录意图和有效知识上下文中的内容追问直接执行已有授权检索，记录 `mode=retrieval` 与零模型调用，正常保留任务锁、版本和幂等；新话题不附加旧文档标题。目录或无匹配检索由服务器按当前租户、ACL 和发布版本直接生成事实答复，不增加模型轮次复述目录；无匹配与没有可见已发布文档分别表达。引用包含版本和位置，打开原文时重新授权。文档正文和模型引文不复制到 LangGraph 检查点；派生回答在权限或来源变化时清除。生产检索使用 PostgreSQL GIN，文件解析复用 pypdf / python-docx 并在有界子进程中运行，全文切分复用 LangChain。文档命令继续使用 WorkEvent 同事务、版本检查和幂等，明确的文档目标不生成虚构事项。

知识改进复用 `rank-bm25` 的 BM25Plus 对 SQL 基础顺序前 500 个已授权、当前发布片段重排；其余匹配结果按原顺序接续，完整总数和分页不裁断。同一查询各页使用同一候选头部，排序统计不混入不可见文档。候选查询只加载片段与引用元数据，避免重复加载完整修订正文和原文件。DOCX 使用 python-docx 正文迭代器保留段落、表格的原顺序；来源位置仍以提取文本为准。固定 23 题合成集同题对比和边界测试见 [知识验收](knowledge.md#2026-11-05-词项检索与解析改进验收)。当前没有 Embedding、模型 Rerank 或 OCR，不声称已实现向量混合检索；后续接入仍必须保留当前租户、ACL、版本、预算与来源失效机制。

## 持续运行的企业 Agent（设计增补）

按用户 2026-11-04 的要求，V1 已实现后台持续关注、自主查询、逐事项推进建议、老板待办及结果跟进。采用业务事件与定时触发、Celery 调度、有界 LangGraph 执行图和 LangChain 模型集成；基于可追溯事实，缺数据保持未知，方案按授权与确认规则执行。每轮检查当前权限、事实版本、重复问题与预算，无变化保持静默。运行授权、领域记录、页面与逐阶段测试见 [持续 Agent](continuous-agent.md)。没有依赖图或资源容量事实时，不宣称具备跨项目排产能力。

主动循环独立接入 watch Worker/Beat。确认事件与 WatchWake 同事务，WatchRun/Outbox 持久化调度；每轮最多核对一百项并选择一个事项复用读取图。模型网络调用前释放事务锁，结果写入前再次检查授权及事实/配置。已落库的图步骤可恢复，未知调用不自动重放；每策略滚动二十四小时轮数和企业统一额度共同限制调用。确认决策和实际结果事件也参与变化检查，成功同步时间戳本身不触发重复分析。当前验收以 [持续 Agent](continuous-agent.md) 文末为准；真实外部服务和团队试点仍未验收。

## 历史：Go Runtime Architecture v0.1

以下保留原架构草案作为早期协议背景，不是 V1 Slice 01 的实现描述。

状态：初始化设计草案。本文整理产品讨论中的最终边界；聊天中的示例字段和未来设想不自动成为已实现功能。

## 分层

1. Interaction：人的意图、输入、会话和交互状态。
2. Experience：理解工作契约，生成 Semantic / Interaction / Layout / Render IR，负责体验连续性。
3. Enterprise Work Runtime：语义、工作、上下文、能力、执行、事件与证据。
4. Provider Integration Runtime：发现、Schema 校验、语义映射、Binding、健康和协议适配。
5. 横向 Control Plane：身份、租户、授权、策略、审批、密钥、审计与可观测性。

前两层位于独立的 [Experience Compiler 仓库](https://github.com/SolanZhang/experience-compiler)；本仓库实现 Go Runtime 与 Provider 接口。Runtime 当前采用单进程，不预先拆分微服务。两个仓库通过 JSON 契约连接。

## 两个协议边界

北向：`WorkExperienceContract` 描述工作语义，交给 Compiler 生成 `ExperienceIR`。Core 不指定颜色、像素、卡片或按钮；IR 是编译器产物。

南向：外部系统实现自描述的 Provider Protocol。Capability 表达业务意义，Binding 表达调用方式。OpenAPI、MCP、A2A、事件等是待实现的 Binding 适配方式；本骨架不宣称兼容其具体版本。

## 架构不变量

- Core 不包含 SAP、CRM 厂商或某家企业的特例。领域概念由 Domain Pack 声明。
- 既有系统保留事实所有权；投影、推导和原始事实必须可区分。
- Provider 注册不授予权限。能力已声明、已授权、当前可执行是不同状态。
- Context 必须先做租户及授权过滤，再交给 Compiler 或模型。
- Human、Agent 和 Service 都通过同一 Capability / Policy 执行路径。
- 所有业务写入都需要 typed ActionRequest、幂等边界与效果验证。
- HTTP 成功不代表业务成功。只有 Verification 通过才可认定完成。
- 写操作默认绑定具有相应事实权威的 Provider。
- Experience Compiler 不持有企业凭据，不直接调用企业 API，UI 确认不等于服务端审批。
- 核心正确性不依赖 LLM；失败不得伪装为成功或破坏 Core 状态。

## 存储与演进

当前无数据库和持久化。第一版持久化计划使用 PostgreSQL 保存注册表、工作、执行、决策和证据元数据，使用事务 Outbox 连接事件。图查询首先建立在资源与关系表上；专用图数据库和独立事件集群需要实际需求后再引入。

协议版本、领域 Schema 版本、Capability 版本分别演进。`v0.1` 尚未冻结；破坏性更改必须更新 Schema、双端模型、样例和测试，并记录迁移说明。


## 决策经验与偏好

阶段 6 复用现有 LangChain / LangGraph、确认图、事务与检索。MemoryEntry 绑定已确认决策/实际结果或本人明确输入，确认前不参与后续查询，来源更新后要求复核；MemoryUse 管理派生结果失效。Owner 私有偏好不共享，经验仅在当前授权事项范围内使用。命令先取得组织 NO KEY UPDATE，再等待在途读取并清理新依赖，避免来源删除与引用插入竞争。详见 [决策记忆](decision-memory.md)。


阶段 7 标准身份由 Authlib 处理 OIDC/PKCE/JWKS，服务端仍独立校验租户成员权限；SMTP 复用 aiosmtplib，邀请 outbox 与幂等收据同事务，Celery/Beat 有限重试和未知结果人工核对。limits 使用共享 Redis，生产预检和独立 TLS 模板保持实际服务验收门槛。详见 [身份与部署](identity-deployment.md)，本地协议验收不等于公开部署。
