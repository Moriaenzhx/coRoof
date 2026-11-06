# coRoof V1 领域模型（Slice 01–02 与模型层阶段 1）

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
| UpdateDraft | 原文、受校验建议字段、作者、事项版本、草稿版本、有效期、pending/confirmed 状态、Provider；0019 增加可选 decision_id，将安排反馈绑定同企业、同事项的已确认安排。 |
| Invitation | 企业/部门、受邀邮箱、角色、邀请人、令牌摘要、期限、撤销/接受状态。不能用于升级已有成员权限。 |
| LoginChallenge / AuthSession | 全局身份令牌摘要及过期时间。挑战一次性，会话可退出注销。 |
| AuditEntry | 企业、操作者、动作类型、对象 ID、UTC 时间；不默认复制敏感原文。 |
| AnalysisRun | 可选草稿或问答作者、purpose/model/provider/prompt_version/input_evidence_ids/output_schema_version/latency/status/cost/time、经过校验的回答。规则成本为 0，模型成本未知记 unknown。 |
| ModelInvocation | 迁移 0003 追加：租户、主体、分析、内部请求指纹、模型/配置/协议/提示/Schema 版本、供应商请求 ID、用量、预算占用、期限与状态。没有返回 usage 时用量为 null；中断调用为 unknown，不自动重放。 |
| AgentExecution | 迁移 0018 追加：企业、AgentRun、queued/running/stopped 状态、投递代次、可投递时间与执行租约；同企业同运行唯一。只保存显式交互读取的执行意图，不授予新权限。 |
| EvidenceSnapshot | 企业 + 事项 + 工作版本唯一；固定当时的结构化事实、最近业务事件摘要、来源时间和事件 ID。读取仍检查当前事项权限。 |
| Signal | 企业 + 事项 + category 唯一；active/resolved、severity、rule_version、evidence_id、评估时间和 version。不是新的业务事实。 |
| Decision | 固定分析、证据、信号版本与选项；pending/confirmed、选择、处理方案、跟进安排、确认者和时间。 |
| DecisionOutcome | 追加实际结果、确认者、时间和同一事项证据引用；不自动改变工作状态。 |
| KnowledgeDocument / KnowledgeRevision | 租户、作者、可见范围、当前发布/待确认版本、内容摘要和版本；作者确认发布，已发布修订不可编辑；原始文件与提取文本保留关联。 |
| KnowledgeReader / KnowledgeChunk | 指定成员 ACL 与带位置的检索片段；查询先限制当前权限和发布版本，未发布资料不进入 Agent。 |
| MemoryEntry / MemoryUse | 决策与实际结果绑定的经验、本人输入的私有偏好；候选经作者确认后有效；源版本更新需复核，删除清除派生结果；所有引用带租户复合外键。 |
| KnowledgeUse | 文档与 AgentRun 的租户复合引用；发布/撤权/撤回/删除使依赖结果失效，并清理内容缓存。 |

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
| 信号/证据/问答 | 本企业事项 | 本部门或分配给自己的事项 | 分配给自己的事项（API） |
| 决策准备/读取/确认/记录结果 | 本企业；准备只引用本人问答或已完成 Agent 分析；确认限准备者本人 | 不允许 | 不允许 |
| 已确认安排与成员反馈的受限读取 | 本企业获授权事项 | 本部门或分配给自己的事项 | 分配给自己的事项 |

权限在每个请求重新读取，移交事项后旧负责人不能再读/确认旧草稿。公司级项目可以被看到其中获授权事项的成员读取；事项列表仍单独过滤。敏感财务数据本轮不存在。AI 问答与证据读取复用这些范围，不能信任模型传入的角色。

## 状态、事务与幂等

- 生命周期仅 `planned / in_progress / done / cancelled`。阻塞独立为 needs_support，能与进行中同时存在。
- planned 可进入 in_progress/done/cancelled；in_progress 不可退回 planned；done/cancelled 不可继续进展更新。结束时解除有效支持标记，原事件保留。
- 生成或编辑草稿只写 UpdateDraft/AnalysisRun。编辑检查 expected_revision。确认检查草稿作者、期限、revision、事项权限与 base_version。
- 确认在一个事务中锁草稿、锁事项，追加 WorkEvent、更新事项投影和草稿状态、写审计。SQLAlchemy version 列另提供乐观并发防护。
- `(organization_id, draft_id)` 唯一；`(organization_id, actor_id, idempotency_key)` 唯一。相同确认返回原 event；同键不同 payload 返回 409，不能二次影响状态。快捷更新和分配同样带幂等键与事项版本。
- 外部 authority 的工作拒绝本地更新；只有活动连接与已映射来源可见。只读连接器离线实现见 Slice 03，真实联调待验收。
- WorkEvent 的 source_ref 指向原始草稿或明确的 Native 操作。原文不是事实生成指令，不触发日期推断、身份绑定或工具调用。

草稿只支持摘要、生命周期和支持需求。规则模式只保守提示支持需求，原文保留；“晚到两天”不会擅自修改截止日期或声称精准分析。用户可编辑并确认。多人参与需求出现后增加关联表，不向 owner_id 塞多个 ID。

## 覆盖与时间

部门没有工作记录时显示“未知 / 无数据”；已有工作记录只代表已覆盖，不能据此断言运行正常。驾驶舱统计来自已授权数据库事实，统计所有分页范围，记录范围和最新更新时间；包含获授权外部投影时标记为部分覆盖，不声称已完整掌握源系统。UI 使用组织时区展示，截止时间输入明确使用当前设备时区，再转换为 UTC。输入 API 必须包含时区。

## Slice 02 一致性

业务事件与信号投影在同一事务更新；读取信号和问答时刷新时间触发规则。模型网络调用前释放工作锁，准备/确认决策时重新锁事项并校验工作版本、整组有效信号版本和三十分钟有效期。明确确认与结果追加分别写 WorkEvent 和审计，不自动解除阻塞或完成事项。相同请求幂等重放；同标识不同内容拒绝。详见 [Slice 02](slice02.md)。

模型层阶段 1 在网络前以短事务记录待完成 AnalysisRun / ModelInvocation；调用返回后重新校验当前权限，失权时不保存或返回回答。AnalysisRun 的 provider/model 表示最终结果来源，failure_code 记录脱敏失败类别；实际模型尝试独立留在 ModelInvocation。模型失败后规则答案的来源是 rules，但已经发送的模型调用费用仍为 unknown。调用记录是技术审计，不作为新的 WorkEvent。

企业 AI 管理增加 AISettings、AIConnection、AIConfigEvent，全部带组织归属。连接与配置、调用记录间使用复合租户外键；密文绑定企业及连接 ID。只有当前 Owner 可保存、测试、启用或撤销连接，员工与部门负责人仅查看本人用量。配置采用版本检查、组织行锁及追加技术审计；连接创建和测试使用幂等键。业务任务与合成连接测试分别计数，Token 观测与保守预算占用分别展示，账单金额仍未知。详见 [企业 AI 管理](ai-management.md)。

## 只读连接器（阶段 4）

0008 新增 Connector、SyncRun、SourceRecord、SourceLink、SourceMember、SyncOutbox。配置保存加密凭据和明确范围，任务关联发起 Owner 与连接版本；来源快照不可变，稳定链接维护映射/隐藏状态，Outbox 提供事务投递。所有关联使用租户复合外键；来源链接还绑定同一连接的快照。WorkEvent 同事务记录 source.synced / source.withheld，外部内容的日期/支持需求未知。详情与离线边界见 [Slice 03](slice03.md)。持续 Agent 的策略/授权/待办记录见下文阶段 8 与 [持续 Agent](continuous-agent.md)。


阶段 6 中，WorkEvent 的事项、文档、经验/偏好目标必须恰有一个；偏好命令不生成虚构事项。经验事件关联原决策事项，偏好事件关联 MemoryEntry。Decision.version 同时作为实际结果来源版本时钟；追加结果使旧经验停止检索。已确认经验向有相同事项权限的 Owner 可见，未确认候选及私人偏好只对作者可见。模型生成内容只是候选解释，不能替代来源实际结果。


阶段 7 新增 LoginAttempt 全局一次性登录收据、Identity issuer/subject 绑定和会话身份模式。Invitation 加入身份模式及请求幂等指纹；InvitationDelivery 使用组织/邀请复合外键、加密投递包、版本、租约和显式未知状态。邀请/投递属于身份治理审计，不制造工作进展事件；加入仍需当前有效邀请人和受邀邮箱，开发身份不会自动获得真实身份权限。

阶段 8 的 0012–0016 追加 WatchPolicy / WatchGrant / WatchCommand、WatchWake / WatchRun / WatchOutbox 以及 AttentionItem / AttentionReview。策略是 Owner 明确确认的目标与有限授权；Grant 绑定身份、策略版本及期限，不保存浏览器会话。AgentRun.watch_grant_id 受租户外键和只读/明确事项约束。关注项按策略与事项/决策去重，只存来源引用、状态和用户核实备注，不替代真实工作进展。所有组织关联均使用租户复合外键。Decision.follow_up_at 是可选的明确时间，不能从跟进文字推断。到期无实际结果形成跟进待办，追加结果只标记 result_recorded，不自动判为问题解决。

## 持久交互查询与安排反馈（0018–0019）

`0018_agent_execution` 新增 AgentExecution，并通过 `(organization_id, run_id)` 复合外键绑定 AgentRun；同一企业同一运行至多一条执行意图。`generation` 必须至少为 1，只有 running 状态可以且必须持有 `lease_token / lease_until`，queued/stopped 清除租约。投递及过期恢复分别按可执行时间和租约索引扫描。`submit` 在同一事务保存本人明确请求的只读运行和执行意图，Worker 复用既有读取图、幂等及模型预算；GET 只读取运行，取消、失权、原会话失效与来源变化阻止后续执行，未知模型调用不自动重放。执行意图不是 WorkEvent，不增加业务事实或 WatchGrant 授权；旧任务不回填为自动执行。详见 [读取循环](agent-read-loop.md)。

`0019_arrangement_feedback` 为 UpdateDraft 增加可空的 `decision_id`，并为 Decision 增加 `(organization_id, work_item_id, id)` 唯一约束。草稿以这三个字段建立复合外键，不能引用另一企业或另一事项的安排；旧草稿保持空关联。安排的创建与确认仍走原 Owner 决策权限，成员仅通过专门的受限输出读取当前获授权事项中的已确认 `selected_plan / follow_up / follow_up_at / confirmed_at` 及成员反馈，不获得未确认方案、其他选项或私有分析上下文。

安排反馈复用 UpdateDraft，不另建反馈事实表。服务器在创建、读取、编辑和确认时重新核对当前事项权限及已确认安排；草稿使用 `manual_feedback`，只保存成员输入的实际情况摘要，不调用模型。作者明确确认前没有反馈业务事件；确认继续检查作者、草稿修订、24 小时有效期、事项版本和可更新状态，并在原事务中追加 `decision.feedback` WorkEvent、更新草稿状态、事项更新时间/版本及相关投影和审计。事件通过草稿关联原安排，重复确认返回原事件；移交失权、跨企业、非作者和过期版本不得提交。反馈拒绝生命周期或支持标记字段，不自动完成事项、解除支持需求，也不新增 DecisionOutcome；记录反馈不等于安排完成或老板已确认实际结果。

两项迁移在已有相应执行意图或反馈关联时均拒绝直接降级丢弃数据。这里描述当前模型和领域实现，不代表后续界面或实际服务已经验收；分阶段交付见 [Yuxi 对照改进](yuxi-improvements.md)。
