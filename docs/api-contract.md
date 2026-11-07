# Slice 01–02 API 契约

版本：`/api/v1`。机器可读的唯一 DTO 来源为 FastAPI OpenAPI；`packages/api-client/openapi.json` 和 `schema.d.ts` 由脚本生成。浏览器用 openapi-fetch，不能编辑生成类型来掩盖服务端不一致。

```sh
cd backend
uv run python ../scripts/export_openapi.py
cd ..
npm run api:generate
```

## 请求边界

除健康、runtime、请求验证链接、验证链接外都要求服务端会话。组织接口要求 `X-Organization-Id`，它只选择租户，不授予权限。写入要求 `X-CoRoof-Request: 1`，浏览器 Origin 必须匹配 `COROOF_WEB_ORIGIN`；跨站请求拒绝。没有 CORS 通配授权。Web 经同源 `/api` 代理请求 Python API。

登录验证使用 Cookie，不在 localStorage 保存会话；邀请采用 URL fragment，避免出现在 HTTP 请求日志，接受后从地址中清除。mock token 只在开发响应中给出，不打印或存明文令牌。浏览器刷新需要重新获取数据库状态，不依赖预置示例。

| 路径 | 语义 |
| --- | --- |
| POST /auth/request-link, /auth/verify | 模拟邮箱投递及一次性挑战验证 |
| GET /auth/me; POST /auth/logout | 当前身份/企业成员关系；注销当前会话 |
| POST /organizations; GET /organizations/current | 新企业及 Owner 成员关系；当前企业 |
| GET/POST /departments | 分页读取；Owner 创建 |
| GET /members; GET /members/{id} | 受权限过滤的成员范围 |
| GET/POST /members/invitations | 邀请列表；创建短期邀请 |
| POST /members/invitations/{id}/revoke, /members/invitations/accept | 撤销；受邀邮箱接受 |
| GET/POST /initiatives | 读取/创建项目容器 |
| GET/POST /work-items; GET /work-items/{id} | 读取/创建事项；mine=true 进一步筛选本人 |
| PATCH /work-items/{id}/assignment | 管理者分配、带 expected_version 和 idempotency_key |
| POST /work-items/{id}/updates | progress/done/support/resolve_support 快捷动作 |
| GET /work-items/{id}/events | 分页追加事件与来源 |
| POST /work-updates/drafts | 生成 RulesProvider 草稿，不更新业务状态 |
| GET/PATCH /work-updates/drafts/{id} | 仅作者读取/编辑；编辑带 expected_revision |
| POST /work-updates/drafts/{id}/confirm | 带 expected_revision；重复确认返回原 event |
| GET /dashboard | 当前授权范围的事实汇总、覆盖、来源、时间 |
| GET /signals; GET /signals/{id} | 当前获授权工作上的规则提示；列表读取刷新时间规则 |
| GET /evidence/{id} | 不可变事实快照，重查当前权限并标记版本过期 |
| POST /ai/ask | 当前权限范围内最多 20 项工作；返回证据、模式与建议，无业务执行 |
| GET /ai/usage | UTC 自然月统计：Owner 看企业，其他成员仅本人；未知用量与未对账费用明确表达 |
| GET /ai/providers | 支持的供应商协议与默认端点目录，不等于全部模型均已实测 |
| GET/PUT /ai/settings | Owner 读取/按 expected_version 保存模式与额度；平台额度受部署上限约束 |
| GET/POST /ai/connections | Owner 列出最多 100 项 / 幂等创建加密连接；仅返回密钥尾号 |
| POST /ai/connections/{id}/test | Owner 显式合成材料测试；expected_version + idempotency_key，实际调用计入额度 |
| POST /ai/connections/{id}/revoke | Owner 按版本撤销凭据，正在使用时同时暂停连接 |
| GET /ai/config-events | Owner 读取最近 50 条配置审计，包含操作者与版本，无凭据明文 |
| POST/GET /decisions; GET /decisions/{id} | Owner 从本人有效分析准备方案或读取组织决策历史 |
| POST /decisions/{id}/confirm | Owner 明确选择、处理方案、跟进安排及版本；同内容幂等 |
| GET/POST /decisions/{id}/outcomes | Owner 分页读取/幂等追加实际结果与证据引用 |
| GET /runtime | 明确开发模式及部署前置条件 |
| GET /healthz, /readyz | 进程存活；数据库及迁移版本就绪 |

列表结构为 `items, total, offset, limit`；默认 50，最大 100。Web 翻页收集获授权数据，不把第一页当作企业总量。驾驶舱不是分页列表；最多约 50 人企业使用同一租户事实汇总。

## 错误及重试

统一结构：`{"error":{"code":"stable_code","message":"可展示说明"}}`。

- 401：未验证/会话失效。
- 403：企业或管理范围越权，Origin/CSRF 校验失败。
- 404：对象不存在或不在授权范围，避免泄露跨租户存在性。
- 409：stale_work / stale_draft / idempotency_conflict / terminal_work / write_conflict 等。
- 422：字段格式、长度、时区等无效；不回显秘密或原始请求。
- 503：数据库不可用或迁移未完成。

相同快捷更新/分配重试应复用幂等键和原 payload。网络结果未知时不得换键盲目重复提交。草稿确认以 draft_id 和 revision 标识同一请求。过期或事项版本变化时保留用户输入，刷新事实、重新生成待确认草稿；不能静默覆盖并发修改。

决策准备与结果追加携带 `idempotency_key`。确认以决策 ID 和请求指纹重放；准备/确认校验三十分钟有效期、工作版本及完整信号集合。409 后保留输入，重新询问获取当前依据；不能覆盖已确认选择。

`GET /decisions` 支持 `mine`（默认 false，true 按服务端当前成员匹配发起人）、`initiative_id`（按当前授权事项的项目过滤）和 `view=all|action_required|pending|follow_up|recorded`（默认 all）。所有筛选在分页和总数统计前执行。列表项为 `DecisionListOut`，增加服务端按租户统计的 `outcome_count`；其他单条/写入响应继续使用 `DecisionOut`。待处理包含未确认方案、已确认且尚无实际结果的方案；未来跟进安排仍可查看，已有结果仅表示追加过记录，不表示事项已完成或问题已解决。个人、企业和项目入口复用原记录，不创建另一套待办事实；Owner、租户及来源可见性约束保持不变。

## 阶段 4：只读连接器

Owner 管理 `/connectors`：POST 保存但不调用外部服务，GET 分页；`/{id}/state` 显式启用/暂停/撤销；`/{id}/credentials` 轮换加密凭据并重回待测试；`/{id}/mapping` 保存状态/成员映射，随后重新全量同步。修改均要求当前版本，读取无密钥明文。

`/{id}/syncs` POST 202 创建 verify/full/incremental 持久化任务，使用 UUID 幂等键与配置版本；GET 分页查看状态，`/{id}/syncs/{run_id}/cancel` 按运行版本取消。`/{id}/sources`、`/{id}/members` 分页返回当前活动来源的待映射信息；失权/暂停后不返回缓存。`/work-items/{work_id}/source` 按当前事项权限提供来源、原更新时间、最近读取与同步异常。工作、证据、分析与决策接口均受当前来源可见性约束。

DTO 以 Pydantic/OpenAPI 为准，见自动生成的 `packages/api-client`；完整语义与尚未完成的真实联调见 [Slice 03](slice03.md)。
## 阶段 5 企业知识库

`GET/POST /knowledge/documents` 提供授权列表与草稿保存；`POST /knowledge/import` 接受受限 TXT/MD/PDF/DOCX 的 Base64 文件并保存提取草稿。文档详情与 `revisions/{revision_id}` / `file` 每次重查当前 ACL。`edit`、`publish`、`access`、`action` 使用版本和幂等键；发布限草稿作者并要求 `confirm: true`，撤回/删除也单独确认。文档内容和文件不得进入错误响应或日志。

`GET /knowledge/search?q=...&offset=...&limit=...` 只返回当前可读的已发布版本及原文位置，limit 不超过 20。Agent 能力 `knowledge.search` 限定用户原始问题、最多 3 个片段；回答在 `documents` 与 `document_answers` 中返回严格验证的引用。事项专属 Agent 不扩大到企业文档范围。OpenAPI 与生成客户端是唯一 DTO 来源。


阶段 6 提供 `/memory/entries`、`/{identifier}/edit`、`/{identifier}/action` 和 `/memory/search`；编辑/确认携带 expected_version、expected_source_hash 与幂等键。Agent 支持 memory_draft 与 memory_entry_id，相关事项由服务端来源推导；AnswerOut 增加带种类的 memories 及严格原文 memory_answers。全部 DTO 以 OpenAPI 和生成的 api-client 为准。


阶段 7 接口：`POST /auth/oidc/start` 返回可信身份服务授权 URL，`GET /auth/oidc/callback` 验证后仅创建本地会话；`POST /auth/logout-all` 撤销本人全部 coRoof 会话。正式邀请响应返回 DeliveryStatus 而非令牌；创建需要 idempotency_key，`POST /members/invitations/{id}/retry` 需要 expected_version、confirm=true 和 idempotency_key，失败与 unknown 不自动视为已送达。邀请列表提供投递状态，服务器始终检查当前组织/部门权限。DTO 已由 OpenAPI 生成。

## 持续关注与老板待办（阶段 8）

- `GET/POST /watch/policies`、`POST /watch/policies/{id}/edit` 与 `/actions`：当前 Owner 管理本人授权，创建/编辑含显式 confirm、期限、范围、额度与幂等键，变更含期望版本；暂停/撤销使旧 Grant 派生结果失效。
- `GET /watch/attention?include_closed=false`：最近一百条本人授权下的关注项，每次读取核验来源和当前权限；返回范围缺口、规则提示或实际完成图的引用。
- `POST /watch/attention/{id}/actions`：snooze/dismiss/correct/reopen，版本与幂等；纠正需要核实备注，只改变待办状态，不产生业务 WorkEvent。
- `GET /watch/policies/{id}/runs`：最近二十轮状态、停止原因与实际核对数量；已授权不等于后台已经完成检查。
- `DecisionConfirm.follow_up_at`：可选明确时刻，未来一年内；省略时不猜时间，旧幂等收据仍兼容。后台建议准备/确认继续走原决策接口及 LangGraph 人工确认，当前 Grant 和事实在确认前再次核验。

后台 HTTP DTO 不接受 Grant 或调用凭据，也没有无人确认的业务写入接口。时间为 UTC ISO8601，页面按组织时区展示，本机 datetime 输入明确标注。最终生成式定义以 `packages/api-client/openapi.json` 为准。
