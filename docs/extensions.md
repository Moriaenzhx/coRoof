# 后续扩展边界（设计契约，尚未实现）

## Slice 02：规则、证据、分析、决策

现有接缝：`WorkEvent` 是稳定事实入口；`get_work / work_scope / member_scope` 是权限入口；`UpdateProvider` 只接收已授权输入并返回 `ProposedFields`，没有数据库连接、凭据或执行工具。`AnalysisRun` 已包含最小审计元信息。本轮只有 RulesProvider。

下一轮通过追加迁移引入 Signal、Evidence、Decision、DecisionOutcome。规则只消费已授权事实：明确阻塞、逾期未完成、临近节点与阻塞；无更新只能标为数据陈旧。每条分析记录 evidence_refs、分析版本和时间，不能编造统计指标。

新增模型 Provider 必须使用配置选择供应商，以 Pydantic 校验结构化结果，保留 rules_fallback 与错误状态。外部文本、资料和提示注入都是数据；不能修改系统指令或授权范围。不要默认把全文写入分析日志。结果改变业务前仍需人确认。

Decision 的选项和 context_snapshot 固定在记录中；确认时重新校验租户、角色、信号与版本。Owner 明确选择后才变更决策；禁止通过 AI 建议发外部消息或改源系统。确认越权测试必须随着真正的决策接口补充，本轮只验证未开放路径返回 404。

## Slice 03：只读连接器

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
