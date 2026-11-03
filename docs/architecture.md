# coRoof V1 Architecture

当前实施边界：Phase 0 + Slice 01（2026-11-03）。模块化单体；Next.js 与 FastAPI 同源代理，API 和 Worker 共享 Python 领域代码，PostgreSQL 保存业务事实，Redis 只负责队列。原有 Go 模块单独保留，暂不参与此业务闭环。

```text
Browser (Owner / Manager / Member)
  -> Next.js /api proxy
  -> FastAPI identity + membership scope + typed command
  -> PostgreSQL transaction: WorkItem projection + WorkEvent + audit

Raw text -> UpdateProvider (RulesProvider)
  -> validated UpdateDraft + AnalysisRun
  -> explicit author confirmation + version check
  -> same transactional work/event path

Celery + Redis -> shared Python modules (currently read-only ping only)
```

API 层不依赖组件，DTO 由 OpenAPI 生成。组织和角色在服务器读取；数据表使用租户复合外键。任何 AI/连接器都只能在相同事实与授权边界接入。详情见 [领域模型](domain-model.md)、[API](api-contract.md)、[ADR](adr/0001-stack.md) 与 [后续扩展](extensions.md)。

空库只通过 Alembic 迁移建结构，不自动填入虚构数据。首次登录后由用户建立企业。默认 mock 身份与规则草稿只用于本地开发，production 模式失败关闭。Compose 以独立 migrate 进程先迁移，再启动 API/Worker。

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
