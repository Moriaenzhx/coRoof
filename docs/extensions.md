# 后续扩展边界

## Agent 能力层（阶段 2–3 已实现）

V1 暂不接入 Skills；以老板需求维护版本化业务能力目录。模型只提出能力及业务参数，服务端按当前权限、对象范围、确认条件和额度决定是否执行，并固定映射到底层工具。知识、经验与偏好也遵循相同边界。详见 [Agent 能力与执行边界](agent-capabilities.md)。当前读取、更新草稿、引用决策与人工确认已接入 LangChain / LangGraph；后续逐项接入连接器、知识和记忆。

## Slice 02：已实现的扩展接缝

Signal / EvidenceSnapshot / Decision / DecisionOutcome 已通过追加迁移 0002 实现；当前模型、权限、时间规则和运行方式见 [Slice 02](slice02.md)。WorkEvent 保持事实入口，get_work / work_scope 保持授权入口。AnalysisRun 记录结构化问答结果与审计元信息，配置式模型适配器只返回受限建议；未配置或失败时明确降级。

Decision 固定当时的事实、信号版本和选项；Owner 明确确认并记录实际结果。没有外部执行工具、长期偏好学习或跨系统写操作。只读连接器已有离线实现，决策记忆已按 [阶段 6](decision-memory.md) 完成开发验收。

## Slice 03：只读连接器

当前离线实现、框架复用、可靠投递与待真实联调边界见 [Slice 03](slice03.md)。以下保留接口设计目标；当前支持显式配置单个范围，未实现自动范围发现和 webhook。

后续 Connector 接口至少包含：

```text
verify_connection(organization, credential_ref) -> connection status
discover_scope(authorized_scope) -> paginated scopes
initial_sync(scope, page_token?) -> records + next page + cursor
incremental_sync(scope, cursor) -> records + next cursor
normalize(source_record) -> proposed facts + unresolved identity mappings
receive_webhook(verified_receipt) -> optional intake
```

SourceRecord 保存 organization_id、connector_id、source_type、external_id、version/payload_hash、JSONB raw_payload、observed_at。去重键至少覆盖 organization + connector + external_id + version/hash。SourceLink 保存稳定本地映射；无法确认成员或项目身份时等待人工绑定，不让模型自行关联。

新增 SyncRun / WebhookReceipt / Outbox，事务中保存原文与待处理消息，Worker 重试必须幂等。支持分页、限流、退避、重放、同步失败与覆盖/最后同步时间。Source of truth 由显式配置维护，保留 WorkItem.source_authority 防护。先用脱敏 fixture 验证飞书项目和 GitLab，只读联调依赖用户授权的凭据，不影响现有 Native 流程。

## Slice 04：决策记忆

DecisionOutcome 存实际观察结果、确认人、时间和 evidence_refs。OwnerPreference 存组织、Owner、key/value、proposed/confirmed/revoked 状态及确认/更新时间。模型只可提出；Owner 显式确认才生效，并支持查看、修改、撤销、删除。

历史检索先按租户与角色过滤，再以 SQL/文本检索检索背景、选择和实际结果。参考案例同时展示失败与冲突，不只迎合偏好。业务事实、模型推断、老板偏好分开。只有真实文档量和查询需求证明必要时再启用 pgvector；不引入独立向量数据库或多 Agent 系统。

所有后续变化采用新 Alembic 迁移和版本化 DTO；不要修改已部署的初始迁移或删除可重放的原始事实。
