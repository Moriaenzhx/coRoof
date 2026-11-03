# Slice 01 API 契约

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
