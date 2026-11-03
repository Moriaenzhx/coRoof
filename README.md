# coRoof

**面向 10–50 人小企业的运行与决策中心。当前交付：V1 Phase 0 + Slice 01。**

老板建立企业、部门和项目，邀请成员并分配事项；员工在移动网页中更新进展、完成或提出支持需求。文字更新先成为可编辑草稿，确认后才产生持久化业务事件。老板从组织全景下钻到人员、工作和原始来源。没有工作记录的部门显示“未知 / 无数据”。

本轮保留原有 Go Runtime 与协议文件；新增 Next.js / FastAPI 模块化业务应用。二者当前不互相调用。设计取舍见 [ADR 0001](docs/adr/0001-stack.md)，真实实现与历史草案分别维护。

## 本地启动

需要 Docker Engine 和 Compose v2+，在仓库根目录运行：

```sh
sh scripts/dev.sh
```

打开 [Web](http://localhost:3000)；[API 文档](http://localhost:8000/docs)。首次启动自动建立 PostgreSQL、执行 Alembic 迁移、启动 API、Redis、Worker 和 Web。配置参考 `infra/.env.example`；所有宿主端口只绑定 127.0.0.1，不连接外部系统。可用 `docker compose --env-file infra/.env.example -f infra/compose.yaml up --build -d --wait` 指定配置。

开发验证不会发送邮件。输入测试姓名和邮箱 → 获取开发链接 → 明确确认模拟身份 → 建立企业。通过“组织与工作”建立部门、邀请、项目和事项。受邀者用对应邮箱完成模拟验证后打开邀请链接加入。生产环境启动被明确阻止，正式身份和邮件服务尚未接入。

已有 PostgreSQL / Redis 的原生启动、完整测试与手工验收步骤见 [开发说明](docs/v1-development.md)。

```sh
sh scripts/smoke.sh
cd backend
uv run python ../scripts/acceptance.py --base-url http://localhost:3000
```

验收脚本通过 HTTP 创建**带标识的虚构验收企业**，数据实际持久化在本地库；不会自动向空库填充示例，也不会发送真实邀请。

## V1 工程目录

| 路径 | 内容 |
| --- | --- |
| apps/web | 老板四页、部门/人员/事项抽屉、响应式我的工作、交互测试 |
| backend/app | 权限、身份、组织、成员、项目、事项、规则草稿与数据库模型 |
| backend/migrations | Alembic 初始迁移，禁止应用启动时 create_all |
| backend/worker | Celery Worker 基线及可重试的无副作用 smoke 任务 |
| backend/tests | PostgreSQL/SQLite 集成验收、租户隔离、权限、幂等、并发 |
| packages/api-client | 从 FastAPI 生成的 OpenAPI 与 TypeScript 类型 |
| infra / scripts | Compose、Dockerfile、环境示例、启动/检查/HTTP 验收 |
| docs | [架构](docs/architecture.md)、[领域模型](docs/domain-model.md)、[API 契约](docs/api-contract.md)、[后续边界](docs/extensions.md)、[验收报告](docs/verification.md) |

本轮不含真实 LLM、飞书/GitLab、Signal/Decision、长期记忆或对真实系统的写操作。重要决策页明确未启用。规则降级不是 AI 分析，开发身份不是生产认证。

## 早期 Go Runtime（原始说明保留）

以下内容记录最初 Go 骨架的定位和路线，不代表当前 V1 的已交付范围；下一阶段以 `docs/extensions.md` 为准。

**AI 原生企业工作环境 · AI-native enterprise work environment**

coRoof 将企业现有系统、业务语义、能力、Agent、治理与体验生成组织在一起，让人围绕目标和工作行动。本仓库是 Go 实现的 Enterprise Work Runtime。

> pre-alpha 初始化骨架。协议为可演进的 v0.1 草案；尚未实现生产鉴权、持久化、真实企业执行或完整 UI。

## 架构

Human / Agent → [Experience Compiler](https://github.com/SolanZhang/experience-compiler) → Work Experience Contract / ActionRequest → **Go Runtime** → Provider → ERP / CRM / HR。

Core 描述工作、事实与能力，未来负责受控执行；Compiler 将授权过滤后的工作契约转为 Experience IR。系统差异位于 Provider 边界，Core 不包含厂商专用业务逻辑。身份、策略、效果验证与证据约束整个执行路径。

## 开始开发

需要 Go 1.26+，在本仓库根目录运行：

```sh
go test ./...
go run ./cmd/coroof validate-provider examples/provider.json
go run ./cmd/coroof serve
```

服务默认监听 127.0.0.1:8080，仅提供 GET /healthz 和 /version；可用 serve -addr 127.0.0.1:9090 修改地址。Provider 校验仅验证离线文件，不进行远程发现、注册或执行。roundtrip-work 命令仅用于契约序列化测试，不代替 Schema 校验。

## 目录

| 路径 | 职责 |
| --- | --- |
| cmd/coroof | CLI 与进程入口 |
| internal/server | 健康检查与版本 HTTP 接口 |
| pkg/contract | Go 工作契约类型 |
| pkg/provider | Provider Manifest 与离线校验 |
| spec | JSON Schema 草案（Apache-2.0） |
| examples | 虚构协议样例（Apache-2.0） |
| docs | 架构、模型、开发说明与路线图 |

Go module 为 github.com/SolanZhang/coRoof。体验编译器在独立仓库中构建；本仓库构建不需要 Node.js。

当前已实现工程结构、协议草案、离线校验、健康检查和基础测试。下一条完整业务链路是合同审批：发现 → 授权上下文 → 工作契约 → 体验 → 治理执行 → 效果验证 → 证据与事件 → 重新编译。

阅读 [架构](docs/architecture.md)、[核心模型](docs/core-model.md)、[协议](spec/README.md)、[开发说明](docs/development.md) 和 [路线图](docs/roadmap.md)。

## License

除明确列出的例外外，本仓库代码和文档采用 [GNU AGPL v3 only](LICENSE)（SPDX: AGPL-3.0-only）。spec/ 与 examples/ 中的协议资料和虚构样例采用各自目录内的 Apache-2.0 许可证，便于独立实现和集成。Experience Compiler 单独采用 Apache-2.0。
