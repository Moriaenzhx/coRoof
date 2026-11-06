# coRoof

**面向 10–50 人小企业的运行与决策中心。V1 八阶段的本地开发验收已通过；真实外部与生产验收仍待完成。**

老板建立企业、部门和项目，邀请成员并分配事项；员工在移动网页中更新进展、完成或提出支持需求。文字更新先成为可编辑草稿，确认后才产生持久化业务事件。老板从组织全景下钻到人员、工作和原始来源。没有工作记录的部门显示“未知 / 无数据”。

本轮保留原有 Go Runtime 与协议文件；新增 Next.js / FastAPI 模块化业务应用。二者当前不互相调用。设计取舍见 [ADR 0001](docs/adr/0001-stack.md)，真实实现与历史草案分别维护。

## 本地启动

需要 Docker Engine 和 Compose v2+，在仓库根目录运行：

```sh
sh scripts/dev.sh
```

打开 [Web](http://localhost:3000)；[API 文档](http://localhost:8000/docs)。首次启动自动建立 PostgreSQL、执行 Alembic 迁移、启动 API、Redis、Worker、Beat 和 Web。配置参考 `infra/.env.example`；所有宿主端口只绑定 127.0.0.1，默认不发起外部连接。可用 `docker compose --env-file infra/.env.example -f infra/compose.yaml up --build -d --wait` 指定配置。

开发验证不会发送邮件。输入测试姓名和邮箱 → 获取开发链接 → 明确确认模拟身份 → 建立企业。在“团队”或“项目与事项”页点击“组织与工作”，建立部门、邀请、项目和事项。受邀者用对应邮箱完成模拟验证后打开邀请链接加入。正式 OIDC/SMTP 接口已实现并完成本地协议验收；缺少实际服务和发布验收时生产启动仍被阻止，当前预览继续明确标记开发身份。

已有 PostgreSQL / Redis 的原生启动、完整测试与手工验收步骤见 [开发说明](docs/v1-development.md)。

```sh
sh scripts/smoke.sh
cd backend
uv run python ../scripts/acceptance.py --base-url http://localhost:3000 --slice02
```

验收脚本通过 HTTP 创建**带标识的虚构验收企业**，数据实际持久化在本地库；不会自动向空库填充示例，也不会发送真实邀请。

完整经营演练见 [星桥软件多角色案例](docs/enterprise-rehearsal.md)：10 人、2 项目、12 项工作，另设外部企业验证隔离。覆盖员工汇报、主管移交、老板决策、实际结果、经验复核和持续关注；提供一键 HTTP 演练、隔离测试及网页体验账号，不接入飞书/GitLab。

## V1 工程目录

| 路径 | 内容 |
| --- | --- |
| apps/web | 企业概览、项目与事项、团队、知识与经验、响应式我的工作及居中按需详情、交互测试 |
| backend/app | 权限、组织工作、规则信号、依据问答、决策与数据库模型 |
| backend/migrations | Alembic 追加迁移，禁止应用启动时 create_all |
| backend/worker | Celery 只读同步、邀请投递、持续关注调度与事务 Outbox 恢复 |
| backend/tests | PostgreSQL/SQLite 集成验收、租户隔离、权限、幂等、并发 |
| packages/api-client | 从 FastAPI 生成的 OpenAPI 与 TypeScript 类型 |
| infra / scripts | Compose、Dockerfile、环境示例、启动/检查/HTTP 验收 |
| docs | [架构](docs/architecture.md)、[领域模型](docs/domain-model.md)、[API 契约](docs/api-contract.md)、[后续边界](docs/extensions.md)、[验收报告](docs/verification.md) |

企业概览先显示动态全景，再看“需要你处理”和“项目进展”，最后是折叠的处理记录与团队动态；同一事项的提醒合并，项目详细状态按需展开。数量来自当前获授权的已记录事项，不当作企业健康或项目完成度。我的工作不铺开空筛选；老板从“等我确认与跟进”处理自己的安排。

工作查询统一使用底部输入框，支持快捷键与浏览器语音转文字；明确发送后持久保存只读请求，由服务器 Worker 在原权限、会话和额度内执行，浏览器只读取进度。在居中的非模态浮层先显示结论与建议下一步，依据、其他选项和处理过程按需展开。切页或关闭浏览器不取消已提交任务；刷新后可找回当前仍获授权的任务，原会话失效或来源变化时停止。“我的工作 → 最近查询”最多展示本人仍可查看的 5 次查询，读取历史不会推进任务或发起模型调用。全局工作、证据、资料原文和业务确认详情改为居中对话框，需要查看时才打开。一次明确查询的继续执行不授予持续关注权限；按目标周期主动运行仍需要 Owner 单独确认有限授权。

继续提问时可关联直接上一轮已完成的本人查询，底部显示“接着聊”并可切换新问题。服务端最多读取直接父轮及更早两轮，总上下文不超过 1,800 字节；每一轮都须属于同企业、本人和原有效会话，创建未满 24 小时，且当前权限与来源版本仍有效。仅提供各轮的有限问题与摘要，直接父轮可附少量来源提示，不递归复制历史上下文，仍须重新读取当前事实。任何纳入的父轮失效时明确提示，只有点击“作为新问题发送”才重新发起独立查询。

本轮按 [Yuxi 对照后的五项改进](docs/yuxi-improvements.md) 分阶段交付。会话执行复用 LangGraph/Celery；知识检索保留 PostgreSQL 全文候选与当前授权，新增成熟 BM25Plus 词项排序、固定 23 题前后评估，并修复 DOCX 段落与表格顺序。Embedding、模型 Rerank 和 OCR 尚未接入，不将词项检索称为语义检索。已通过的阶段结果及后续范围以该计划和对应模块文档为准。

Slice 02 已提供工作上下文问答、规则提示、证据快照、老板确认方案与跟进结果。“处理这件事”先准备本人方案，在居中详情中展示默认安排与跟进建议；可展开修改，再点击“确认这个安排”。打开或准备不等于确认，不自动通知同事或改变工作状态；过期依据需先重新核对，其他人不能代为确认。企业和项目处理记录仍可按需查阅。需要模型判断的 Agent 查询需要已启用且可用的模型服务；配置不可用时明确显示失败，不静默切换成规则回答。明确的资料目录和有效知识上下文中的内容追问可直接读取授权原文，显示“原文检索 · 未调用模型”。既有规则输出仍明确标记来源。通用 MaaS 业务入口尚未完成真实凭据验收，配置、阈值、边界和验收见 [Slice 02](docs/slice02.md)。飞书项目/GitLab 已完成只读离线实现；长期偏好记忆已实现，外部写入未实现，开发身份仍不是生产认证。

员工可在获授权事项中查看已确认安排并提交反馈，反馈由本人确认后供老板查看，不自动改变事项状态或认定安排完成；权限与事务边界见 [领域模型](docs/domain-model.md)。

已按 [V1.0 顺序交付与验收](docs/v1-delivery.md) 的八阶段推进，每阶段通过开发门槛后进入下一阶段；用户明确延后的真实外部项目单独保留发布验收。阶段 1 已接入统一模型入口、百炼 Qwen 配置、调用审计和租户预算，追加迁移为 `0003_model_gateway`。2026-11-04 使用独立 Coding Plan 测试配置完成六组真实 Qwen 开发案例；通用 MaaS 后端验收仍待对应凭据。

2026-11-04 增补 [企业 AI 管理](docs/ai-management.md)：点击侧栏账户可查看 AI 用量；企业所有者可管理平台服务 / 自带凭据、连接测试与启用、额度及操作记录。统一网关提供 OpenAI、Anthropic、Gemini 和 Chat Completions 协议，预设包含百炼与 DeepSeek；兼容服务需部署方允许端点，每个模型组合单独验证。追加迁移 `0004_ai_management`；费用尚未对账，生产身份及正式收费尚未上线。

2026-11-04 按用户要求采用 **LangChain + LangGraph**：模型供应商适配复用 LangChain，Agent 读取执行与检查点复用 LangGraph；企业权限、BYOK、额度、审计和业务事务保持原服务边界。阶段 3 已接通 AI 更新草稿、作者确认、引用决策和结果跟进，复用 LangGraph 人工等待与恢复。实现见 [Agent 提案](docs/agent-actions.md)、[模型层](docs/model-layer.md) 和 [交付记录](docs/v1-delivery.md)。

阶段 4 使用 python-gitlab、飞书项目薄适配、Celery/Beat 与 Tenacity，实现加密连接、显式测试/启用、分页/增量、人工映射、来源追踪、撤权隐藏和故障恢复，详见 [Slice 03](docs/slice03.md)。账户菜单提供“外部连接”；阶段 8 的持续 Agent 在此来源基础上独立实现规划、关注与跟进。

阶段 5 [企业知识库](docs/knowledge.md) 已提供文档导入、作者确认发布、版本/权限、授权检索和 Agent 原文引用。目录及空检索答复使用服务器实际授权结果；无匹配不等于没有文档，最多列出 20 篇当前可见的已发布资料并说明总数与截断。撤回、修改权限或删除后，相关旧分析失效；不将制度要求当作工作已完成的事实。阶段 6 [决策经验与偏好](docs/decision-memory.md) 已完成来源绑定、AI 候选、作者确认、私有偏好与带条件引用；后续结果改变后要求复核。Owner 在“个人设置”通过“查看以前的处理经验”核对决策经验，并管理本人 AI 偏好，不再增加主导航入口。阶段 7 [身份与部署](docs/identity-deployment.md) 已通过 OIDC/SMTP 本地协议、备份恢复和部署配置验收；真实身份服务、邮件和域名待接入。

阶段 8 的入口为账户菜单“持续关注”。Owner 明确确认范围、目标、期限、核对节奏和分析额度后，后台可在浏览器关闭时继续读取；主页展示有依据的待办。暂停/撤销使旧派生答案不可用，缺数据保持未知，无变化不重复调用。方案与实际结果仍需本人确认；可设置明确的跟进时间。使用与故障边界见 [持续 Agent](docs/continuous-agent.md)。真实团队试点仍待完成。

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
