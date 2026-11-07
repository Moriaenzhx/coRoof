# ADR 0001：以模块化单体交付 coRoof V1

日期：2026-11-03。状态：采用，仅覆盖 Phase 0 / Slice 01。

## 背景与取舍

检查时仓库工作树干净，没有 AGENTS.md；已有 Go 1.26 骨架、协议草案、离线 Provider 校验、健康检查及测试。没有数据库、用户身份或业务实现。V1 的产品边界来自本轮实施任务书：10–50 人企业的运行与决策中心。

保留 `cmd/`、`internal/`、`pkg/`、`spec/`、`examples/` 及其 CI，不改动或调用 Experience Compiler。不把旧协议当作已实现的 V1 业务。新增 Next.js App Router、React、TypeScript 与 FastAPI/Pydantic 2 业务应用，独立于原 Go 工程构建。两者当前不互相调用，后续是否整合需另做 ADR；避免为了空壳兼容层增加双后端业务写入。

主库 PostgreSQL 16；SQLAlchemy 2 显式事务；Alembic 是唯一建表和迁移入口。SQLite 只用于快速测试，不代表生产并发保证。PostgreSQL 测试验证行锁和复合外键。

API / Celery Worker 共享 Python 领域代码。Redis 是任务传输层，不保存业务事实。Slice 01 的确认事务同步提交；仅配置无副作用的 Worker ping，不在提交前异步投影。后续分析通过事务 Outbox 接入，不能在事务外直接发布后声称可靠送达。

## 身份与部署

本轮提供显式 mock 验证链接和邀请投递。令牌仅存 SHA-256 摘要，登录验证十分钟有效且一次性，邀请二十四小时有效并可撤销；邀请接受必须匹配已经验证的邮箱。会话为 HttpOnly / SameSite=Strict Cookie，有效期二十四小时。所有组织权限来自数据库中的有效 Membership，客户端不能自报角色。

mock 不验证真实邮箱所有权，故 `COROOF_ENVIRONMENT=production` 直接拒绝启动。即便配置真实邮件地址，也不意味着真实认证。正式身份 Provider、发送器、HTTPS、审计日志策略、限流、备份恢复和部署审查是试点上线前置条件。

## 视觉与范围

通过获授权的 Sites 元数据取得用户指定原型的发布截图。采用原型的浅色侧栏、简洁导航、左侧摘要与右侧环形组织图、详情抽屉。移动端将运行图转为单列部门摘要。六个以上部门使用规整列表避免节点拥挤。没有 AI 对话框、财务指标、健康评分或虚构风险。

重要决策仅保留原型导航及明确未启用页面。Signal、Decision、SourceRecord、SourceLink、长期记忆均不在本轮建表或开放接口。后续契约见 [扩展边界](../extensions.md)。

## 依赖与生成文件

Python 3.12、`uv.lock`；Web Node 22.12+（开发测试工具要求）、`package-lock.json`。FastAPI 导出 OpenAPI；`openapi-typescript` 生成 TypeScript Schema，`openapi-fetch` 以 Schema 约束真实请求。禁止手写第二套 DTO。

Next.js 16.4.4 的 `next dev` 自动新增了 `apps/web/AGENTS.md`；该文件已读取并保留。与检查开始时没有 AGENTS.md 的事实区分。新增依赖经 npm audit 检查；minimatch override 修复 OpenAPI 工具链的传递依赖公告，Vitest 升级至 5。
