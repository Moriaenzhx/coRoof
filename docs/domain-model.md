# coRoof V1 领域模型（Slice 01）

本文件描述已经落库的模型；协议层的历史草案见 `core-model.md`，不能替代这里的业务约束。

| 实体 | 当前规则 |
| --- | --- |
| Organization | UUID、名称、IANA 时区、UTC 创建时间。根租户本身以 id 标识。 |
| User | 全局、唯一验证身份、显示名、身份 Provider 标记。加入多个企业需分别创建 Membership。 |
| Membership | organization_id、user_id 唯一；roles 支持 owner/manager/member 兼任；status active/inactive；本 Slice 一个所属部门。 |
| Department | organization_id + name 唯一；负责人由该部门有效的 manager Membership 推导，不维护第二份负责人状态。 |
| Initiative | 容器，标题/目标/部门/负责人/截止时间/status。公司级项目仅 Owner 创建；负责人仅管理所属部门项目。 |
| WorkItem | 所属部门、可选项目/负责人/UTC 截止时间，四种生命周期、version、updated_at、source_authority。needs_support 为事件投影。 |
| WorkEvent | 追加事实：主体、参与身份、事件类型/内容、发生及记录时间、来源标识、请求指纹。无修改和删除 API。 |
| UpdateDraft | 原文、受校验建议字段、作者、事项版本、草稿版本、有效期、pending/confirmed 状态、Provider。 |
| Invitation | 企业/部门、受邀邮箱、角色、邀请人、令牌摘要、期限、撤销/接受状态。不能用于升级已有成员权限。 |
| LoginChallenge / AuthSession | 全局身份令牌摘要及过期时间。挑战一次性，会话可退出注销。 |
| AuditEntry | 企业、操作者、动作类型、对象 ID、UTC 时间；不默认复制敏感原文。 |
| AnalysisRun | 企业、草稿、purpose/model/provider/prompt_version/input_evidence_ids/output_schema_version/latency/status/cost/time。规则模式成本为 0。 |

除全局身份/会话/挑战与租户根外，业务表都有 `organization_id`。跨表业务关联使用 `(organization_id, id)` 复合唯一约束与外键，不能把乙公司的部门、成员、草稿或事项挂入甲公司。主键为 UUID 文本；PostgreSQL 使用带时区时间戳与 JSONB。必要的租户、范围、事件时间索引在初始迁移中定义。

## 权限范围

| 行为 | Owner | Manager | Member |
| --- | --- | --- | --- |
| 组织/部门 | 企业全局；创建部门 | 读取本部门 | 读取所属部门名称 |
| 查成员 | 企业有效成员 | 本部门及本人 | 仅本人 |
| 邀请 | 任一部门 member/manager | 仅本部门 member | 不允许 |
| 创建/分配工作 | 本企业所有部门 | 本部门 | 不允许 |
| 读/更新工作和事件 | 本企业 | 本部门或分配给自己的事项 | 分配给自己的事项 |
| 草稿读取/编辑/确认 | 仅本人且仍有事项权限 | 同左 | 同左 |
| 决策确认 | 接口未启用 | 接口未启用 | 接口未启用 |

权限在每个请求重新读取，移交事项后旧负责人不能再读/确认旧草稿。公司级项目可以被看到其中获授权事项的成员读取；事项列表仍单独过滤。敏感财务数据本轮不存在。将来 AI 检索必须复用这些范围，不能信任模型传入的角色。

## 状态、事务与幂等

- 生命周期仅 `planned / in_progress / done / cancelled`。阻塞独立为 needs_support，能与进行中同时存在。
- planned 可进入 in_progress/done/cancelled；in_progress 不可退回 planned；done/cancelled 不可继续进展更新。结束时解除有效支持标记，原事件保留。
- 生成或编辑草稿只写 UpdateDraft/AnalysisRun。编辑检查 expected_revision。确认检查草稿作者、期限、revision、事项权限与 base_version。
- 确认在一个事务中锁草稿、锁事项，追加 WorkEvent、更新事项投影和草稿状态、写审计。SQLAlchemy version 列另提供乐观并发防护。
- `(organization_id, draft_id)` 唯一；`(organization_id, actor_id, idempotency_key)` 唯一。相同确认返回原 event；同键不同 payload 返回 409，不能二次影响状态。快捷更新和分配同样带幂等键与事项版本。
- 外部 authority 的工作拒绝本地更新。本轮不存在实际连接器或外部同步。
- WorkEvent 的 source_ref 指向原始草稿或明确的 Native 操作。原文不是事实生成指令，不触发日期推断、身份绑定或工具调用。

草稿只支持摘要、生命周期和支持需求。规则模式只保守提示支持需求，原文保留；“晚到两天”不会擅自修改截止日期或声称精准分析。用户可编辑并确认。多人参与需求出现后增加关联表，不向 owner_id 塞多个 ID。

## 覆盖与时间

部门没有工作记录时显示“未知 / 无数据”；已有工作记录只代表已覆盖，不能据此断言运行正常。驾驶舱统计来自已授权数据库事实，统计所有分页范围，记录范围和最新更新时间；外部系统固定为尚未接入。UI 使用组织时区展示，截止时间输入明确使用当前设备时区，再转换为 UTC。输入 API 必须包含时区。
