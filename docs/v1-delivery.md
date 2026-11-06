# V1.0 顺序交付与验收

按用户 2026-11-03 的执行要求，以下阶段依次推进；一个阶段的验收未通过时继续修正，不越过门槛进入下一阶段。测试、模拟联调和真实外部验收分别记录。已交付的 Phase 0 / Slice 01–02 保留，历史 Go Runtime 与共享协议独立。

2026-11-04 用户修订验收顺序：先使用已有 Coding Plan 完成开发流程的真实模型验收，流程跑通后再测试通用 MaaS。通用 MaaS 的账号、业务端点与部署验收移到发布前，不再阻塞阶段 2 的实施。开发验收使用显式配置与明确标识的合成数据，复用实际业务实现；开发测试通过不等同于通用 MaaS 或商用部署通过。下文较早的“等待通用凭据后进入阶段 2”记录为历史状态，以本项修订为准。

| 阶段 | 交付                   | 必须通过的验收                                                         | 当前状态                              |
| ---- | ---------------------- | ---------------------------------------------------------------------- | ------------------------------------- |
| 1    | 统一模型层与 Qwen 适配 | 协议/异常测试、PostgreSQL 隔离/预算/升级、真实 Qwen 合成案例、全栈回归 | 开发门槛通过；通用 MaaS 验收延后至发布前 |
| 2    | Agent 读取闭环         | 问题触发授权查询、证据回答、取消/预算/恢复、越权不执行                 | 已通过（LangChain / LangGraph）        |
| 3    | Agent 草稿与决策       | 提案、作者确认、版本冲突、重复确认一次效果、结果跟进                   | 已通过                                |
| 4    | 只读连接器             | 飞书项目/GitLab 分页与增量、幂等、映射、撤权、故障恢复                 | 离线验收通过；真实联调延至发布前        |
| 5    | 企业知识库             | 文档权限、索引与来源、删除/撤权传播、带引用问答                        | 开发门槛通过                          |
| 6    | 决策经验与偏好         | 来源与实际结果、候选确认、修改/撤销/删除、检索隔离                     | 开发门槛通过                          |
| 7    | 真实身份与部署         | OIDC/SMTP 本地协议、会话/限流、备份恢复；真实服务发布前验收 | 离线开发门槛通过；真实服务发布前验收 |
| 8    | 持续 Agent 与完整试点 | 主动规划/关注/跟进、端到端流程、费用/性能/权限、真实团队试用          | 本地开发门槛通过；真实团队试点待验收 |

## 阶段 1 验收入口

从 `backend/` 使用独立 PostgreSQL 测试库执行：

```sh
COROOF_TEST_DATABASE_URL='postgresql+psycopg:///coroof_v1_test_1103?host=/tmp' .venv/bin/pytest tests/test_model_gateway.py tests/test_slice02.py -q
```

完整回归按 [开发说明](v1-development.md) 执行。迁移新增 `0003_model_gateway`，不重置原库；正式升级前备份。模型调用前记录 pending 并释放工作锁，进程中断或响应未知时不自动重试，保留预算占用。规则降级准确标识最终来源，模型尝试单独记录。

真实验收使用允许后端用途的百炼通用 API，只发送明确标识的合成材料。配置忽略的 `infra/.env`：`COROOF_AI_PROVIDER=bailian`、`COROOF_AI_MODEL=qwen3.7-plus`、对应地域/业务空间的 `COROOF_AI_BASE_URL` 和 `COROOF_AI_API_KEY`。Coding Plan 凭据不能用于此入口。

```sh
backend/.venv/bin/python scripts/model_acceptance.py --env-file infra/.env
```

脚本最多执行六次计费调用，验证正常建议、无数据、其他企业请求、陈旧记录、原文冲突和提示注入；报告保存到忽略的 `.local/model-acceptance.json`，不写密钥、原始供应商错误或隐藏推理。未配置返回退出码 2，测试失败返回 1，全部通过返回 0。真实结果通过并检查报告后，才设置 `COROOF_AI_MODEL_VERIFIED=true`；更换端点、模型或配置需重新验收。

按用户 2026-11-04 的明确要求，另增独立的 Coding Plan 开发测试入口：

```sh
backend/.venv/bin/python scripts/model_acceptance.py \
  --config-file .local/coding-plan-test.json \
  --report .local/coding-plan-acceptance-v2-60s.json
```

该私有 JSON 配置权限为 `0600`，已排除 Git 和 Docker 构建上下文；不读取现有进程环境或环境文件，不调用本地模型、不访问业务数据库。配置字段为 `provider`、`model`、`base_url`、`api_key`，可选 `timeout_seconds`（默认 60，最大 120）。它只在显式测试入口使用，不启用业务后端，也不能设置通用 MaaS 的 verified 标记。报告分别标识 `deployment_kind=bailian_coding_plan_test` 和 `application_backend_verified=false`。

当前预算按租户限制滚动 24 小时调用次数、token 和并发；不是金额硬上限。无 usage、网络超时和中断调用保守保留估计 token 占用，费用仍记 unknown。未知价格不能声称免费或给出虚构费用。Legacy Chat Completions 配置保留已有显式启用行为，并不因此获得 Qwen 的 verified 标记。

## 外部验收依赖

发布前需要百炼通用 API 配置；阶段 4 需要允许访问的飞书项目与 GitLab 测试范围；阶段 7 需要真实身份/投递服务、域名和部署目标；阶段 8 需要实际参与试用的团队。依赖未就绪时，记录可复现的具体阻塞，不能以 fixture、mock 身份或本地演示代替真实验收。

## 阶段 1 当前验收结果（2026-11-04）

| 检查                    | 结果                                                                                                            |
| ----------------------- | --------------------------------------------------------------------------------------------------------------- |
| PostgreSQL 全部后端测试 | 74 passed；包括原 Slice 01–02 回归、并发额度、锁等待期限、撤权、升级和显式测试配置隔离                           |
| SQLite 辅助回归         | 70 passed，4 个 PostgreSQL 专用并发/锁测试明确跳过                                                              |
| 旧库升级保留            | 独立测试 schema 中从 0002 升到 0003；原有事项与分析内容保持，Alembic metadata 无漂移；PostgreSQL/SQLite 均通过  |
| Python 静态检查         | Ruff、53 文件格式、39 源文件 mypy 通过                                                                          |
| Web                     | 格式、类型、15 项交互测试、Docker standalone 构建通过；OpenAPI/client 已重新生成                                |
| Go                      | vet、race tests、构建及离线 Provider 校验通过                                                                   |
| 后端镜像                | 使用本机缓存且已核实版本的 uv 0.13.6 完成构建；原始构建的 GHCR 元数据请求等待无结果后取消，仓库 Dockerfile 未改 |
| Qwen 远端连接           | Coding Plan / qwen3.7-plus 返回 HTTP 200，连通测试约 1.24 秒                                                  |
| Qwen 六组开发案例       | 6/6 通过；补充 Schema 提示后严格结构与引用校验通过；P50 6.415 秒、最大 10.135 秒；60 秒测试期限                |
| 通用 MaaS 后端验收      | 尚未执行；Coding Plan 结果不代表通用端点、账号权限或生产部署已验证                                             |

初次六组实测中，四组因缺少必填 `action_keys` 被严格校验拒绝，另两组通过；补充 Schema 提示后的一次探测超过原 25 秒期限。失败报告保留在忽略的 `.local/` 中，未伪装成成功或自动重试。随后在显式 60 秒测试配置下完整六组通过，费用仍记 unknown；这组有限案例不等同于长期稳定性或通用 MaaS 验证。

阶段 1 的开发测试已推进，但整体门槛仍未全部通过，阶段 2–8 尚未开始。服务器通用 MaaS 需要对应端点和凭据；可通过独立 JSON 或部署密钥注入，不要求读取本机已有模型环境。没有迁移或重置用户已有业务库，没有公开部署。

## 阶段 1 授权增补：企业 AI 管理（2026-11-04）

按用户随后授权增加多供应商统一协议、账户设置入口、企业用量、平台服务/BYOK、加密凭据、连接测试与明确启用、日/月 Token 额度和配置审计。实现与边界见 [企业 AI 管理](ai-management.md)。按协议测试 → PostgreSQL 管理验收 → 页面交互/完整回归依次完成；阶段 2–8 的外部验收门槛不因此跳过。

当前 PostgreSQL 95 项、SQLite 90 项（5 项跳过）、Web 21 项通过；Python/Web 静态检查、Go 检查及两端镜像构建通过。与上面的历史记录不同，本次已先备份再对本地 Compose 库追加 `0004_ai_management`，原业务记录数量保持，未重置数据。开发预览已更新；新多供应商测试为合成 HTTP fixture，不能替代各家真实账号、业务质量或正式商业部署验收。

## 用户新增要求：复用 LangChain / LangGraph（2026-11-04）

在进入第三阶段前先迁移模型调用与 Agent 读取执行图。供应商协议复用 LangChain，检查点复用 LangGraph 官方数据库实现；coRoof 保留企业密钥、权限、额度、事实验证、确认与事件事务。最终 PostgreSQL 133 项、SQLite 127 项（6 项跳过）、Web 28 项、静态检查和构建通过，Coding Plan 真实三场景通过。0006 本地迁移与页面复核通过，原业务数据数量保持。第三阶段在该门槛通过后开始。

后续第三阶段的人工等待/继续使用 LangGraph interrupt/Command 接入现有草稿、决策与结果服务；第四至八阶段保持原业务范围与逐阶段测试要求。框架的存储能力不替代文档权限、经验来源、偏好确认或真实身份/外部验收。

## 阶段 3 验收（2026-11-04）

已接入 LangChain 更新提案、现有 UpdateDraft 编辑与作者确认、LangGraph interrupt/Command 等待与恢复，以及 Agent 引用回答到 Decision 和实际结果的闭环。详见 [阶段 3 实现](agent-actions.md)。新增迁移为 0007_agent_drafts。

新增 13 项 PostgreSQL 图与事务验收通过。全量 PostgreSQL 145 项通过，唯一失败是旧测试仍期待 0006；改为当前 0007 后该项补跑通过，合计 146 项。SQLite 138 项通过、7 项专用测试跳过，同一迁移断言修正后补跑通过，合计 139 项。Web 31 项、类型、格式与完整镜像构建通过。Python Ruff/format/mypy 通过；本轮未修改 Go，沿用框架迁移时已通过的 vet/race/build。

Coding Plan 真实开发验收 6/6 场景通过，其中新增引用决策确认、结果幂等、AI 草稿编辑确认。报告 `.local/agent-actions-acceptance.json`；测试使用隔离 schema 的合成资料，没有发送真实企业工作内容。

本地更新前已备份为 `.local/pre-agent-actions-1104.dump`。标准后端 Docker 构建在远程 uv 镜像元数据查询处等待；依赖未变化，因此使用阶段 2 已验收的依赖镜像复制当前后端源码完成镜像更新。0007 已迁移，API/Web/Worker/PostgreSQL/Redis 健康，Alembic metadata 与 OpenAPI 再生成无漂移。原 4 家企业、3 项工作、12 个事件、3 个草稿、9 条分析、1 个连接数量保持；密钥未进入受版本控制的文件。开发页面已刷新，连续查询入口无浏览器错误；当前企业没有工作，草稿/决策表单由交互测试和隔离的真实模型流程验证。截图为 `.local/agent-actions-desktop.png`，不表示已经在空企业执行过业务更新。

第四阶段优先复用 [python-gitlab](https://python-gitlab.readthedocs.io/en/stable/api-usage.html) 管理 GitLab 协议与分页。飞书项目须核对专用 OpenAPI，不能以普通飞书消息/文档 SDK 代替。已向用户询问测试项目链接和授权范围；尚未连接外部项目，第 4–8 阶段未完成。

## 用户修订：离线连接器与持续 Agent（2026-11-04）

用户没有外部测试项目，明确要求先完成第四阶段离线实现。阶段 4 的开发门槛使用真实 SDK 的合成 HTTP 响应与 PostgreSQL 事务测试，真实飞书项目/GitLab 验收延后到发布前，不能用 fixture 声称已联调成功。

用户同时明确持续运行的企业 Agent 需求：后台自主查询与规划、项目推进建议、事实支持的问题发现及老板待办；无数据不编造。已纳入 [持续 Agent 设计](continuous-agent.md)，阶段 4–7 补齐基础，阶段 8 实现持续关注循环并单独验收；这是设计增补，不是运行功能的通过记录。

## 阶段 4 离线验收结果（2026-11-04）

已完成 [只读连接器](slice03.md) 与管理页面。新增 25 项连接器验收，完整 PostgreSQL **171 passed**；SQLite **163 passed、8 skipped**（行锁/并发专用测试）。Web **36 passed**，Ruff/格式/mypy、Web 格式/类型、Go vet/race/build 与 provider 示例校验通过。OpenAPI/client 再生成无漂移，Alembic metadata 无漂移。标准 Dockerfile 构建 API/Worker/Migrate/Beat/Web 成功，未使用替代依赖镜像。

初次完整回归发现旧测试把无授权来源链接的 external 事项预期为可见但不可写；当前权限规则要求它完全不可见，已修正 404 断言，另有活动来源只读的 409 测试。前端测试最初使用的 DOM 断言扩展与当前 Vitest 类型不匹配，改用标准断言后类型与构建通过。补充“授权失效不能经暂停再启用绕过复测”的回归测试后重新全量通过。

本地更新前已备份 `.local/pre-connectors-1104.dump`，追加 0008 迁移并更新开发预览。原 4 家企业、3 项工作、12 个事件、3 个草稿、9 条分析、1 个模型连接数量保持；没有创建真实企业的合成外部事项。API/Web/Worker/PostgreSQL/Redis 健康，Beat 运行；真实队列 ping、空 outbox 投递与无匹配任务处理通过，无外部网络调用。页面核对了账户入口、空状态、GitLab 与飞书项目配置抽屉。

阶段 4 离线开发门槛通过，真实项目授权、字段与同步联调延后至发布前。阶段 5 企业知识库是下一阶段；持续 Agent 需求已更新第 8 阶段交付目标与第 4–7 阶段接缝，尚未声称自主循环已运行或 V1.0 已完成。

## 阶段 5 验收结果（2026-11-04）

已完成 [企业知识库](knowledge.md)：TXT/MD/PDF/DOCX 导入、作者草稿确认、文档版本及 ACL、中英文检索、原文/原文件、Agent 严格引用问答，以及撤回/撤权/删除的派生结果清理。新增迁移 0009；统一 Agent 提示升级为 agent-read-v3 / agent-proposal-v2，知识正文不写入 LangGraph 检查点。

最终完整 PostgreSQL **201 passed**；SQLite **191 passed、10 skipped**。随后将模型注册统一到 API/Worker/CLI 的数据库入口，知识与连接器 PostgreSQL **55 项补跑通过**。Web **42 passed**；Ruff/100 文件格式/mypy 71 源文件、Web 格式/类型、Go vet/race/build 与 Provider 示例通过；标准 Dockerfile 构建 API/Worker/Migrate/Beat/Web 通过。OpenAPI 再生成和本地 Alembic metadata 均无漂移。

验收中额外发现读取引用写入与文档撤权之间的外键锁等待，改用企业/文档 NO KEY UPDATE，并在清理前等待在途读取事务；专门的 PostgreSQL 并发用例通过。文件测试覆盖文本 PDF、DOCX、扫描/加密/损坏文件与限额；不宣称支持 OCR。开发模型真实验收 **9/9**，包含原工作读取/隔离/无资料、知识引用/私有资料不泄漏/提示注入、决策与结果/草稿确认。报告 `.local/knowledge-live-acceptance.json`，只发送隔离 schema 中的合成资料，不代表通用 MaaS 或真实企业试点通过。

本地升级前已备份 `.local/pre-knowledge-1104.dump`，0009 迁移后 API/Web/Worker/PostgreSQL/Redis 健康、Beat 运行，真实队列 ping 和无匹配同步任务通过。原 4 家企业、3 项工作、12 个事件、3 个草稿、9 条分析、1 个 AI 连接数量保持；未向用户企业填入合成文档。浏览器已复核知识库入口、空状态和新建/导入抽屉，截图 `.local/knowledge-desktop.jpg`。第 6 阶段继续实施；后台自主关注仍按第 8 阶段单独验收，生产身份与真实外部验收仍未完成。


## 阶段 6 验收结果（2026-11-04）

已完成 [决策经验与偏好](decision-memory.md)：经验绑定已确认决策及实际结果、本人私有偏好、严格原文 AI 候选、LangGraph 人工确认、有效经验检索、编辑/撤销/删除和源变更失效。Owner 主导航新增“经验与偏好”，来源、条件和确认状态可见；不自动把模型建议或推测固化为企业事实。迁移为 0010_memory。

完整 PostgreSQL **215 passed**、SQLite **203 passed / 12 skipped**；Web **47 passed**。Ruff/109 文件格式/mypy 78 源文件、Web 格式/类型/生产构建、Go vet/race/build 及 Provider 示例校验通过。原模型迁移测试期待旧 head，修正后纳入最终全量回归；并发新增确认竞争、源变更时拒绝晚到模型输出、删除等待在途读取并清理引用。OpenAPI/client 再生成和 Alembic metadata 无漂移，标准五服务镜像构建通过。

真实 Coding Plan 合成验收 **14/14 场景、21 次调用**通过，报告 `.local/memory-live-acceptance-v3.json`。前两轮在读取第三步遇到输入额度限制，失败报告保留；缩短重复提示并对相同事实引用去重，增加默认额度下的完整开发协议回归后通过，没有放宽生产额度。真实开发流程包含经验/偏好候选确认、严格引用及后续结果要求复核，不代表通用 MaaS 或生产试点验收。

本地迁移前备份 `.local/pre-memory-1104.dump`，追加 0010 后服务健康，Beat 运行，readyz 和队列 smoke 通过。原 4 家企业、3 项工作、12 个事件、3 个草稿、9 条分析、1 个 AI 连接数量保持；知识/经验表均为空，没有写入合成客户数据。浏览器已核对入口、经验来源选择和无结果禁建、本人偏好输入；无浏览器错误，截图 `.local/memory-desktop.jpg`。阶段 7 是下一步，持续 Agent 自主循环仍待第 8 阶段实现验收。


## 阶段 7 验收顺序修订（2026-11-04）

用户确认暂时没有企业登录、邮件服务和部署域名，先完成标准接口和本地验收。第 7 阶段使用 Authlib OIDC、SMTP 协议夹具、PostgreSQL 和页面/部署测试作为开发门槛；真实 IdP、收件箱、域名与生产服务器仍为发布前外部验收。详情见 [身份与部署](identity-deployment.md)。第 8 阶段等待本阶段开发门槛通过，不能把协议夹具称为真实团队联调。


## 阶段 7 离线验收结果（2026-11-04）

已完成 Authlib OIDC/PKCE、签名身份令牌校验、一次性浏览器绑定、mock/真实身份隔离、会话轮换与退出全部设备；正式邀请采用加密事务 outbox、标准 SMTP、幂等和版本、有限重试及 unknown 明确确认。新增 0011_identity，Web 增加正式登录分流、身份标记和邀请投递状态；默认预览仍为 mock。

完整 PostgreSQL **249 passed**，随后新增 CSRF/限流故障拒绝用例补跑 **1 passed**；SQLite **235 passed / 14 skipped**，同项补跑 **1 passed**。Web **53 passed**，Ruff/124 文件格式/mypy 87 源文件、Web 格式/类型与标准五服务镜像构建、Go vet/race/build 和 Provider 示例校验通过。独立 PostgreSQL 旧库迁移、metadata 无漂移、真实 pg_dump/pg_restore、恢复数据核对和拒绝覆盖已有目标通过；初次清理因迁移连接池未释放失败，补充 Alembic 引擎释放后重跑通过。OIDC/SMTP 都是隔离的本地协议验收，没有连接真实企业身份服务或发送外部邮件。

独立生产 Compose 静态校验与隔离网络内 Caddy 配置校验通过；预检不打印秘密，实际外部发布标记保持 false。备份 `.local/pre-identity-1104.dump` 后完成本地 0011 升级，原 4 企业、3 工作、12 事件、3 草稿、9 分析、1 AI 连接、空知识/经验表数量保持。API/Web/Worker/PostgreSQL/Redis 健康、Beat 运行，readyz、Alembic check、OpenAPI 重生成无漂移。停 Worker 后入队 ping 和不存在邀请的任务，重启后正常消费；没有向用户企业写入合成邀请。浏览器复核个人设置与开发身份标记，无 console error，截图 `.local/identity-desktop.jpg`。

阶段 7 开发门槛通过，阶段 8 开始实施；真实通用 MaaS、外部项目、IdP/SMTP/域名和团队试点继续作为发布前外部验收，V1 尚未宣称完成。

## 阶段 8 本地验收（2026-11-04）

持续关注按六个内部门槛依次实现并验收：Owner 有期限的范围授权；事务事件、时钟与可恢复投递；LangGraph 后台读取和 LangChain 模型调用；依据去重的老板待办与推进方案；人工确认/暂缓/纠正/显式到期跟进；故障、额度、队列进程与完整体验。新增迁移 0012–0016，复用原业务事件、授权、模型预算和决策确认，不创建无人确认的业务写入路径。

完整 PostgreSQL **289 passed / 1 skipped**（跳过需显式 Redis 的进程测试），SQLite **270 passed / 20 skipped**。最后针对上下文去重和决策事件变化新增默认额度回归，PostgreSQL **63 项补验通过**；SQLite 原读取与执行 **38 passed / 2 skipped**，后续执行额度 **13 passed / 1 skipped**。显式本地 Redis + PostgreSQL 的独立队列/Worker 停机后投递、两次进程生命周期和重复消息 **1 passed**，没有重写业务事实。

Web 全量 **59 passed**，格式/类型、标准五服务镜像、Python Ruff/147 文件格式/mypy 98 源文件、Go vet/race/build 与 Provider 示例校验通过。浏览器最终核对中发现收起侧栏的账户菜单被滚动容器裁切，改为视口定位并限制高度，补跑原账户与新关注 **14 项交互通过**，再次构建并更新本地 Web。最终浏览器菜单和关注设置显示完整，无 console error，截图 `.local/watch-settings.jpg`。入口在账户菜单“持续关注”；主页保留安静全景，显示少量需要处理的项目，配置和处理仍在详情抽屉中进行。

Coding Plan 真实开发验收 **7/7 场景、6 次模型调用**通过，报告 `.local/watch-live-acceptance-v4.json`。验证离线后读取、严格依据、无自主业务写入、无变化不重复计费、确认一次效果、新决策触发后续规划、无数据零调用及暂停失效。前几轮失败报告保留；合成提案诊断确认后续输入额度失败由重复经过/提示等上下文造成，去重并压缩重复指令后通过，未放宽默认额度。提示版本为 agent-read-v5，已确认决策/实际结果事件进入后台范围指纹及读取经过。所有资料均在随机隔离 PostgreSQL schema 中合成，测试密钥仅来自明确测试配置，不读取企业业务凭据。

本地升级前备份 `.local/pre-watch-1104.dump`，执行 0011→0016；原 4 企业、3 工作、12 事件、3 草稿、9 分析、1 AI 连接及空知识/经验表数量保持。未为真实企业自动创建策略或合成工作。OpenAPI/client 再生成逐字节一致，Alembic metadata 无漂移；API/Web/Worker/PostgreSQL/Redis 健康，Beat 持续运行，readyz 通过。真实通用 MaaS、飞书项目/GitLab、企业 IdP/邮件/域名与真实团队试点仍是发布前外部验收，不能将本地门槛通过称为商用 V1 已上线。

## 八阶段完成性复核（2026-11-04）

本节按完整目标核对证据范围，不以本地开发门槛替代发布完成。运行状态来自本地 API 进程配置和数据库只读查询，脱敏结果位于 `.local/release-audit-runtime.json`。当前 migration head 为 0016_attention，服务健康；身份与投递均为 mock，OIDC/SMTP 未配置，发布验收标记 false。已保存一个 Coding Plan 开发连接，其他模型连接为零；平台模型密钥和端点未配置，模型验证标记 false；连接器和关注策略均为零。这些空值不表示已在真实企业完成过对应流程。

| 阶段 / 不变量 | 当前证据与覆盖 | 完成判断 |
| --- | --- | --- |
| 1 统一模型与 Qwen | `test_model_gateway.py`、`test_ai_management.py` 验证多协议、异常、预算、凭据与租户隔离；Coding Plan 合成报告与后续 Agent 报告验证真实开发模型 | 开发通过；通用 MaaS 和其他供应商真实账号未验收 |
| 2 Agent 读取 | `test_agent_read.py`、`test_frameworks.py` 验证授权能力、限步、取消、检查点、未知调用恢复；后续知识/记忆报告覆盖真实执行图 | 本地与 Coding Plan 开发通过 |
| 3 草稿与决策 | `test_agent_actions.py` 验证作者确认、过期、版本、并发和一次效果；真实合成报告验证决策/结果与更新草稿 | 开发通过；没有无人确认的业务写入 |
| 4 飞书项目 / GitLab | `test_connectors.py` 验证 SDK/协议夹具、分页、映射、撤权、恢复和事务投影；数据库当前无连接 | 离线通过；缺真实测试项目与授权 |
| 5 企业知识库 | `test_knowledge.py`、`test_knowledge_agent.py` 与真实合成报告验证导入、作者发布、ACL、引用、撤回与失效 | 开发通过 |
| 6 决策经验与偏好 | `test_memory.py` 与 14 场景真实开发报告验证来源/实际结果、本人确认、私有偏好、修改撤销及检索失效 | 开发通过 |
| 7 身份与部署 | `test_identity.py`、`test_invitations.py`、`test_deployment.py` 验证 OIDC/SMTP 本地协议、会话、投递恢复、预检和真实 PostgreSQL 备份恢复 | 本地通过；缺真实 IdP、邮件服务、域名和服务器验收 |
| 8 持续 Agent 与试点 | `test_watch_*`、真实 Redis/Worker 进程测试、7 场景 Coding Plan 报告及页面核对验证关注、去重、预算、确认跟进与恢复 | 本地通过；真实团队效果、生产容量与实际费用未验收 |
| 租户 / 事件 / 迁移 / 确认 | PostgreSQL 完整回归及最终补验覆盖复合外键、并发、撤权、事件原子性、版本/幂等；0011→0016 数据保留和 Alembic check | 本地证据通过；未修改独立 Go/spec 协议 |

复核发现部署预检和备份 CLI 的 dotenv 默认插值仍可能引用进程环境，违反“显式文件为唯一配置来源”。已关闭两处变量插值，私有文件须填写完整值；增加回归验证本机变量不能提供发布确认，也不能替换备份/恢复目标，拒绝时不访问数据库或运行原生工具。PostgreSQL 部署验收 **5 passed**，包括实际备份恢复；Ruff/147 文件格式/mypy 98 源文件通过。Worker 文档等待时间同步为模板中的 180 秒。未改变业务运行配置、未调用外部服务，未开启发布标记。

下一步真实验收需要：通用 MaaS 的明确模型/端点和业务凭据；有授权的 GitLab/飞书测试项目；可信 IdP、可收信测试邮箱与 SMTP、域名和部署目标；实际试用团队及其允许处理的数据范围。上述输入仍未提供，保持未验收状态。凭据通过企业设置或服务器私有配置提供，不写入聊天或版本库；材料齐备后按各阶段原有测试和真实流程继续验收。

## 用户指定的完整模拟经营验收（2026-11-04）

按用户要求，暂不连接飞书/GitLab，创建“星桥软件”10 人虚构企业，另设外部企业账号验证隔离。2 个项目、12 项事项贯穿员工汇报、主管移交、老板决策、实际跟进结果、经验复核与持续关注。设计、角色账号、重跑命令和完整结果见 [多角色经营演练](enterprise-rehearsal.md)。

真实本地 HTTP/Worker 链路 **72 项断言通过**，老板/主管/员工浏览器操作通过。真实 Qwen 开发模型最终 **7/7 场景、7 次调用通过**；保留所有前期失败报告，十轮诊断/复测累计 29 次模型调用。测试使用独立 schema 的合成经营资料和显式开发配置；当前网页中的演练企业保留规则模式，模型服务与关注授权暂停，方便继续查看且不留下持续执行任务。

演练暴露丰富历史导致的输入预算问题，以及部分模型输出的状态/引用混淆。模型上下文与 Schema 去除重复展示开销，不再列出已用能力，最后一步只保留回答上下文；工作、文档和记忆引用的说明更明确，仍保留严格的服务器校验。离线最深六步图在默认输入上限内通过，决策与实际结果经过仍完整保留；提示版本更新为 `agent-read-v6`。

最终 PostgreSQL **301 passed、无跳过**（包含真实 Redis/Worker）；SQLite 全量 **279 passed、20 skipped**，后续相关回归 **82 passed、4 skipped**；Web **59 passed**。Python Ruff/150 文件格式/mypy 98 源文件、Web 格式/类型/构建、Go vet/race/build/Provider 校验通过。后端镜像已更新，服务健康；OpenAPI/client 再生成一致，原企业五类业务表按租户核对行数与内容摘要保持。没有新增数据库迁移。此次完成模拟经营验收，真实身份/投递、通用 MaaS 商业入口、生产容量和真实团队试点仍按原发布门槛验收。
