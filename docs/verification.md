# Phase 0 + Slice 01 验收报告

日期：2026-11-03。范围仅为仓库基线与 Native 组织工作闭环；不是生产上线，也没有进入 Slice 02–04。

## 已完成

- 保留原有 Go CLI、协议、示例及测试。检查开始时工作树干净、没有 AGENTS.md；新增根开发约束，保留 Next.js 自动生成的 Web 开发约束。
- Next.js / FastAPI / PostgreSQL / Redis / Celery 工程基线、锁文件、环境示例、健康检查、统一错误、Alembic、生成式 API 类型、本地启动和 CI。
- 开发身份验证、企业初始化、部门、项目、邀请/接受/撤销、多角色成员、创建和分配工作；所有权限由服务端按企业及部门/事项范围校验。
- 移动端我的工作：进展、完成、支持需求、自由文字。文字先生成明确标记为规则模式的可编辑草稿，确认后才写业务事件。保留原文、确认内容、作者、时间及来源。
- 事项状态与支持需求分离；事件与投影同事务提交；草稿/事项版本、行锁、唯一约束与幂等重放防止重复写入。
- 参考指定全景原型实现浅色侧栏、组织运行图、稀疏摘要和详情抽屉；移动端使用单列部门摘要。统计来自数据库，未覆盖部门显示未知，不计算虚构健康分。

## 检查结果

| 检查 | 结果与边界 |
| --- | --- |
| Python Ruff + format | 通过；35 个文件格式检查 |
| Python mypy strict | 通过；26 个源文件 |
| PostgreSQL 集成测试 | **19 passed**，包括 4 个并发确认请求只生成一个事件 |
| SQLite 快速测试 | **18 passed, 1 skipped**；明确跳过 PostgreSQL 行锁并发用例 |
| Alembic | 专用空库 upgrade → downgrade → upgrade 通过；`alembic check` 无模型漂移 |
| OpenAPI / TypeScript 生成 | 重新生成后逐字节一致 |
| Web 格式、类型、构建 | 全部通过；Next.js standalone 构建成功 |
| Web 交互测试 | **6 passed**：草稿编辑确认、失败保留输入、发送中禁重、未知部门、员工范围、开发登录 |
| npm audit | 本机及容器安装均为 **0 vulnerabilities**；不等同于完整安全审计 |
| 原 Go 工程 | `go vet`、`go test -race`、构建、离线 Provider 校验通过；本机 Go 1.26 |
| 原生一条命令启动 | `scripts/native-dev.sh` 实际运行通过；healthz/readyz/Web 同源代理及真实 Celery 排队返回 pong |
| HTTP 业务验收 | 原生与 Compose 环境均通过：3 部门 + 1 项目 → 邀请 → 分配 → 草稿 → 确认 → 全景与来源 → 重复确认一个事件 |
| Compose | `sh scripts/dev.sh`、`sh scripts/smoke.sh` 均实跑通过；镜像构建、空卷初始化、migrate 成功退出、Postgres / Redis / API / Worker / Web 全部健康；容器内 Alembic 无漂移 |
| 服务退出 | 容器直接启动应用进程，Worker 配置 init 与 30 秒退出窗口；重新排队执行 ping 后停止，API / Worker 均以 0 退出，不再被超时强制终止 |
| 浏览器 | Chrome 桌面全景与 400px 移动端通过；真实点击登录、打开本人事项、输入、编辑草稿、确认，事件由 2 条增至 3 条，原文与编辑后内容同时保留 |
| Git / Shell | `git diff --check` 与 4 个 shell 脚本语法检查通过 |

后端用例同时覆盖两家企业的隔离和复合外键、员工越权、部门负责人范围和邀请提权、草稿作者/期限/版本、终态保护、移交后旧权限失效、身份令牌重放/过期、跨站写入和生产 mock 启动阻断。决策接口尚未开放，仅验证不存在的路径返回 404；真正的决策确认权限测试属于 Slice 02。

测试使用独立本地开发/测试库。PostgreSQL 集成用例为每次测试建立随机 schema，结束后只删除自己的 schema。原生验收企业的名称明确包含“验收示例”，邮箱使用 example.com，不代表真实客户或员工。没有访问真实外部业务系统。

本机 Compose 数据卷保留“coRoof 验收示例 · docker1103”。重新启动后，开发登录使用 `owner-docker1103@example.com` 可查看老板全景，`member-docker1103@example.com` 可查看员工事项；姓名任意。这些只是模拟身份，不是生产账号，也不发送邮件。原生数据库与 Compose 数据卷相互独立。验收结束停止本轮服务，数据卷不删除。

## 已知限制与环境处理

- 当前是开发 mock 身份和规则草稿，无法验证真实邮箱所有权；生产模式拒绝启动。正式身份 Provider、邀请发送、HTTPS、安全 Cookie、限流、备份恢复和部署审查仍是上线前置条件。
- 没有真实 LLM、Signal/Decision、飞书/GitLab 同步、长期记忆或外部写操作。重要决策页仅说明尚未启用。
- 测试有一条上游 Starlette TestClient/httpx 弃用警告；未屏蔽，测试仍通过。浏览器未登录时 `/auth/me` 的 401 为预期身份探测；未观察到业务更新的脚本异常。
- GitHub Actions 已配置但没有推送或远端执行；不能将本地结果称为远端 CI 已通过。本机没有运行 Go 1.27 矩阵。
- 最初磁盘不足导致 Docker I/O 错误。按用户补充授权清理 Fielora 与同级项目的依赖、编译/测试产物、旧测试打包应用和两段测试视频，共释放约 29 GiB；保留源码、Git 修改、数据库、文档报告及备份。清理前后 Fielora / Aegis 的 Git 状态一致，明细留在忽略目录 `.local/disk-cleanup.json`。
- Docker Hub 的认证域名在本机超时，使用 [Docker 在 ECR Public 发布的官方镜像](https://aws.amazon.com/blogs/containers/docker-official-images-now-available-on-amazon-elastic-container-registry-public/)预取 Node / Python 基础镜像，再在本地使用其标准标签。没有修改系统 DNS、代理或注册表设置。此前 PostgreSQL Alpine 缓存中的入口脚本为空，移除重拉后仍不可执行；Compose 和 CI 统一使用 PostgreSQL 16 Bookworm 镜像。

## 下一阶段准备

接口与持久层已经留下受限的扩展位置，详细约束见 [extensions.md](extensions.md)：

1. Slice 02：以 WorkEvent 与既有权限过滤为入口，通过追加迁移引入 Signal / Evidence / Decision / Outcome。模型 Provider 只提出经 Schema 校验的建议；增加来源、冲突、过期、无证据与提示注入回归案例。
2. Slice 03：只读 Connector、SourceRecord / SourceLink、同步状态、事务 Outbox、幂等重放和来源权威；先做脱敏 fixture，再由用户提供授权联调。
3. Slice 04：只保存 Owner 明确确认的偏好，提供查看、修改、撤销和删除；检索同时展示历史选择与实际结果，数据量证明必要时才引入向量检索。

主要改动位于 `apps/web/`、`backend/`、`packages/api-client/`、`infra/`、`scripts/`、`docs/` 及根工具配置。运行命令与手工验收步骤见 [v1-development.md](v1-development.md)。未提交、推送或公开部署。
