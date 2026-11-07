# coRoof V1 模型层：统一调用与模型适配

日期：2026-11-03。本文保留完整设计目标与实施前基线。阶段 1 的统一入口、Qwen 适配、调用审计和租户预算已实现，真实模型验收尚未通过；实际进度与测试入口见 [V1.0 顺序交付与验收](v1-delivery.md)。其余设计项不自动视为已实现。基于 Slice 01–02 和 [Agent 能力与执行边界](agent-capabilities.md)，不接入 Skills、历史 Go Runtime 或共享协议。

## 2026-11-04：迁移到 LangChain / LangGraph

按用户最新要求，优先复用成熟框架。模型调用采用 LangChain 的 ChatOpenAI、ChatAnthropic、ChatGoogleGenerativeAI 和 ChatDeepSeek；百炼和其他兼容服务使用 ChatOpenAI 的兼容接口。删除手写 wire.py 和供应商响应归一化器，结构化输出与 Schema 方言转换交给集成包及官方 SDK。ModelGateway 保留任务契约、端点策略、总期限、输入预算和本地严格校验；企业 BYOK/额度/审计仍在原业务模块。

Agent 读取分支由 LangGraph StateGraph 执行，使用官方 PostgresSaver（SQLite 为辅助测试）。检查点表通过 Alembic 0006_langgraph 建立，附加从服务器 thread_id 派生的企业/运行复合外键；运行时不调用 setup 或建表。单轮 checkpoint 绑定企业、任务和步骤，模型输出在保存前及执行前分别复核权限，未知远端调用不自动重放。当前人工确认仍由已有业务接口承担，第三阶段再接入图的人工等待节点。

所有 SDK 显式传入本次企业配置，关闭隐式重试、缓存和 LangSmith 自动追踪；响应读取大小与总期限受限。供应商默认行为不能改变已验收的预算或数据目的地。当前锁文件固定 LangChain 1.4.8、LangGraph 1.2.19 及相应集成包；Anthropic SDK 限定 0.120–0.x，以兼容共用的 httpx 受限传输，不另写一套 SDK 网络协议。升级依赖需重跑多供应商契约测试。

当前五家供应商协议通过本地 HTTP fixture；Coding Plan 的真实 Agent 三场景通过，其他供应商账号与通用 MaaS 商用验收尚未执行。详细验收见 [交付记录](v1-delivery.md)。以下原始设计中的“暂不引入框架”为历史决策，以本次修订为准。

参考：[LangChain 模型](https://docs.langchain.com/oss/python/langchain/models)、[LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)。

## 设计决定

2026-11-04 增补：多供应商协议、企业凭据与配置页面已经进入实施，当前范围和验证结果以 [企业 AI 管理](ai-management.md) 为准。下文“当前接缝”表保留实施前设计基线，不表示新的多协议代码仍未实现。统一接口已支持 Responses / Messages / generateContent / Chat Completions；Azure、Bedrock、Vertex 的原生云鉴权尚未实现，不能因存在兼容入口就宣称这些云平台已通过验收。

业务按任务调用统一 ModelGateway；模型差异由版本化 ModelProfile 和 ProviderAdapter 处理。首个新增适配目标为百炼通用 API 的 `qwen3.7-plus`。先把现有依据问答接入统一入口，再让 Agent Harness 使用相同入口生成能力提案。

统一的是请求、结果、错误和运行记录。模型的思考模式、结构化输出、工具协议、参数限制及提示方式保留独立配置，通过同一组业务评测验证。首期是 Python 单体内部模块，复用 httpx/Pydantic；暂不引入独立代理服务或多模型编排框架。

## 当前实现与需要补齐的边界

| 当前接缝                                  | 已有能力                                      | 下一步变化                                                                    |
| ----------------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------- |
| `intelligence/analysis.py:model_answer`   | Chat Completions、JSON Schema、超时、引用校验 | 拆出网络协议，保留业务校验；请求参数由模型配置决定                            |
| `intelligence/analysis.py:ask`            | 授权证据、释放工作锁、规则降级、AnalysisRun   | 通过任务路由调用 Gateway；分别记录尝试的模型和最终结果来源                    |
| `intelligence/provider.py:UpdateProvider` | 规则草稿、作者确认                            | 保留业务接口，后续 ModelUpdateProvider 委托 Gateway，不把规则实现变成远程模型 |
| `core/config.py`                          | 单组 provider/base_url/model/key              | 拆分部署端点、模型配置和任务路由；凭据仍只在服务器                            |
| `AnalysisRun`                             | 分析结果、模型/提示版本、耗时、粗粒度状态     | 追加模型调用明细，准确表达重试、失败、用量未知和降级                          |

现有适配器向所有兼容端点发送同一组字段，例如 `store:false`、`max_completion_tokens` 和 `response_format`，尚未按具体端点验收。网络异常、拒绝、截断和业务校验失败也集中为同一降级状态。统一接口需要保留这些差异，不能把 HTTP 200 当作有效业务答案。

## 百炼接入边界

官方 Coding Plan 当前列出精确模型 ID `qwen3.7-plus`，国内兼容端点为 `https://coding.dashscope.aliyuncs.com/v1`。该套餐仅允许在指定范围的工具中交互使用，明确排除自定义应用后端和自动批量调用；其凭据与百炼通用 API 不互通。默认和正式部署仍拒绝以此凭据开启应用调用，也不借用编程工具转发业务请求。本轮用户另行要求的单连接本机测试见下，不代表供应商认可该用途。[Coding Plan 官方说明](https://help.aliyun.com/zh/model-studio/coding-plan)

后端使用允许应用调用的百炼通用 API。按实际账号的地域、业务空间和模型授权配置端点；北京地域当前文档推荐 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，原有 `https://dashscope.aliyuncs.com/compatible-mode/v1` 仍可用。不同地域的 Key 不能混用；套餐中可用不代表通用 API 账号已授权。[兼容接口与地域说明](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)

2026-11-04，按用户明确要求，将其测试凭据保存在 Git/Docker 忽略的私有配置中，并直接连接 Coding Plan 远端完成开发探测。显式 `--config-file` 测试入口不读取本机环境变量或 `.env`，不连接数据库；测试配置仅能在 `environment=test` 且 `verification_probe=True` 时使用，不能启用应用业务路由。通用 MaaS 的服务器接入仍单独验收；示例和审计不包含密钥。

真实测试发现 Coding Plan 接受 `response_format` 后仍可能漏掉必填字段。专用 `bailian-coding-plan-qwen37-test-v2` 配置补充 Schema 到系统提示，继续保留本地严格校验；依据问答提示更新为 `evidence-qa-v2`，明确方案字段及其含义。六组开发案例最终通过。一次 25 秒超时保留为失败记录；显式测试配置默认采用 60 秒期限，不修改业务入口的 25 秒默认值。具体结果见 [交付记录](v1-delivery.md)。

2026-11-05 用户明确要求把已有连接用于当前模拟企业的本机流程测试。新增部署侧 `COROOF_AI_DEVELOPMENT_TEST_CONNECTION_IDS`，默认空数组，本轮只指定目标企业的一条独立加密连接。其专用 Profile 为 `bailian-coding-plan-qwen37-local-{schema/json}-v1`，沿用 Schema 提示、本地严格校验和 60 秒单次调用期限；LangChain、任务输出契约与总运行预算不变。服务器同时要求开发/测试环境、mock 身份模式、回环 `web_origin`、精确供应商/模型/端点、允许名单中的受管连接，以及当前企业的 mock 成员身份。Owner 保存、测试、明确启用仍是独立步骤，旧独立探测结果不能替代连接验证。

该例外只向显式连接测试和前台 Agent 交互查询开放，不向平台全局配置、其他模型入口或后台持续关注扩散。非本机、未列入允许名单及生产环境保持拒绝；生产预检拒绝非空开发允许名单。跨企业导入须明确授权并重新绑定加密，不共享原连接或改变原企业配置。具体管理和回退边界见 [企业 AI 管理](ai-management.md#本轮单连接本机测试例外)，通用 MaaS 的实际商用验收仍未由本机测试替代。

## 调用路径与职责

```text
业务服务 / Agent Harness
  -> 当前身份与对象授权 -> 有限的 ContextSnapshot
  -> TaskPolicy：任务、输出契约、允许的模型配置、总预算
  -> ModelGateway：选配置、检查能力、控制期限、归一化结果
  -> ModelProfile：模型版本、能力、参数、提示补充、Schema 方言
  -> ProviderAdapter：协议序列化、鉴权、网络、响应解析
  -> 供应商端点

响应 -> 结构校验 -> 业务证据/提案校验 -> 当前权限复核
  -> 答案或待确认草稿
  -> 只有 Harness 的授权执行器才能执行能力
```

| 模块            | 负责                                               | 不负责                                   |
| --------------- | -------------------------------------------------- | ---------------------------------------- |
| 业务服务        | 授权取数、事实与引用校验、草稿、明确确认、事务     | 供应商请求字段和错误格式                 |
| Agent Harness   | 能力目录、提案授权、步骤预算、取消、工具执行、恢复 | 把模型输出视为权限或执行结果             |
| ModelGateway    | 确定性任务路由、模型能力检查、期限/额度、调用明细  | 查询企业数据库、执行能力、自动升级权限   |
| ModelProfile    | 精确模型与部署组合的能力和优化参数                 | 根据名称猜测能力或宣称更高质量           |
| ProviderAdapter | HTTP/SDK 协议转换、限量读取、结果与用量解析        | 生成业务事实、自动工具回调、决定规则降级 |

Gateway 不拿数据库 Session、工作行锁或业务工具凭据。内部租户/主体标识用于预算与审计，默认不序列化到供应商请求。仅发送已授权且该任务必需的内容；调用返回、读取历史记录、准备或确认写入时均重新验证当前权限。调用期间失权的结果不得返回给已失权主体，也不得作为后续执行依据。

## 内部契约

以下是拟定字段，不是新增公开 API。实现时使用严格 Pydantic 类型，业务输出 Schema 从现有类型生成。公开 DTO 如需调整，仍由 OpenAPI 生成 `packages/api-client`。

| 对象             | 核心字段与约束                                                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| DeploymentConfig | `id`、provider、protocol、base_url、region、credential_ref、允许用途；端点由可信部署配置指定，前端和模型不能覆盖                                       |
| ModelProfile     | `id/version`、deployment_id、精确 model_id、能力状态、上下文/输出上限、Schema 方言、reasoning 参数映射、参数允许列表、prompt_variant_version、验证日期 |
| TaskPolicy       | task_id/version、schema_id/version、允许的 profile_id、有序候选、上下文/时间/调用/费用预算、降级策略；由服务端选择                                     |
| ModelRequest     | request_id、服务端审计作用域、task_id、已过滤 messages/context、schema_id、可选能力提案目录、剩余预算与截止时间；无任意 `extra_body` 透传              |
| ModelResult      | 调用标识、实际 profile/provider/model、结构化输出或提案、finish 状态、token 用量、耗时、供应商请求 ID；缺失用量为 null                                 |
| ModelError       | 稳定错误码、可重试性、脱敏供应商状态、retry_after、用量是否未知；不带密钥、完整请求或原始错误正文                                                      |

能力记录区分 `unknown / documented / verified / unsupported`，覆盖 JSON Schema、JSON Object、tool calling、reasoning、streaming 和输入模态。验证对象是“部署 + 精确模型 + 模式 + Schema 方言”，不能因一个兼容端点通过就把所有同名模型标成 verified。首次人工联调可以使用 documented 配置；自动业务路由只选已通过验收的组合。

结果采用互斥类型：结构化回答、能力提案、拒绝、失败、取消。`finish_reason=tool_calls` 只在提案任务中归一化为待验证提案；普通问答收到工具调用即拒绝。工具名、call_id 和参数只是输入数据，不能触发 SDK 自动执行。

第一版提案路径使用结构化 JSON，每轮最多一个 CapabilityProposal。首个 Qwen 配置不启用供应商内置工具、联网、任意 function calling 或并行执行。以后接入原生 tool calling 时，固定映射到同一能力提案契约；不支持所需模式时在发请求前拒绝，不能静默改变任务语义。

## 模型优化与首批任务路由

| 任务                  | 首期配置                                   | 优化重点                                       | 失败行为                             |
| --------------------- | ------------------------------------------ | ---------------------------------------------- | ------------------------------------ |
| `evidence_qa`         | Qwen 快速结构化配置；未显式启用时 rules    | 关闭思考，有限证据，沿用现有严格引用与建议校验 | 显示规则整理及降级原因               |
| `work_update_draft`   | 保持现有 RulesProvider；模型草稿为后续步骤 | 只提取明确字段，不推断日期/身份；仍由作者确认  | 返回保守可编辑规则草稿               |
| `capability_proposal` | Harness 就绪后启用 Qwen 提案配置           | 按权限裁剪目录，严格参数，单步提案             | 停止并明确失败，规则不能伪装成 Agent |
| `decision_compare`    | 预留 Qwen 推理配置，评测后启用             | 单独思考预算，选项代价/假设/依据，不直接写决策 | 返回未完成；不自动执行或编造比较     |

任务名称只是内部设计。`decision_compare` 不是当前已实现的决策准备接口，不能通过配置提前暴露；知识检索和偏好任务在相应 Slice 获授权前不进入路由。

初期快速问答与提案可以使用同一模型、不同 Profile。服务端按任务选择，模型不能自行挑选更贵的模型或新增供应商。切换模型必须满足任务能力、数据目的地和预算约束；跨供应商备用路由默认关闭。

每个任务保持一份业务系统提示和输出契约，模型配置只补充经评测的表达方式、参数和 Schema 编码。中文业务术语、证据 ID、缺数据表达与禁止执行宣称等约束不能被模型专用提示覆盖。首期沿用问答最多 20 项工作/5 项建议，再增加总输入字节与 token 预算；裁剪完整证据项并更新覆盖数量，不能截断 JSON 或把裁剪后的输入称作全量。

### Qwen 3.7 Plus 首个配置

以下针对百炼通用 Chat Completions API；是待联调配置，不是实测性能结论。

| 项目       | 设计                                                                                                           |
| ---------- | -------------------------------------------------------------------------------------------------------------- |
| 模型标识   | `qwen3.7-plus`；若使用账号已授权的快照则精确记录快照 ID，不能假定套餐接受同一快照                              |
| 思考       | 快速问答显式 `enable_thinking=false`；推理配置单独启用并设置上限，不依赖模型默认值                             |
| 结构化输出 | 首选 `response_format.type=json_schema` 和 `strict=true`；从 Pydantic 生成 Schema 并验证供应商支持子集         |
| 输出上限   | 使用当前 Chat API 文档支持的 `max_completion_tokens`，统一预算包括思考与最终回答；截断即失败，不能补括号当成功 |
| 采样       | 首次保留供应商默认采样；以同一评测集比较参数后固定，不把其他模型的 temperature/top_p 原样复制                  |
| 扩展参数   | httpx 请求中的 `enable_thinking` 放在 JSON 顶层；SDK 的 `extra_body` 包装不是 HTTP 请求字段                    |
| 响应       | 仅最终 `content` 进入业务校验；忽略并不保存 `reasoning_content`，只记录供应商提供的用量统计                    |
| 留存字段   | 不向百炼盲传未经文档/联调确认的 `store` 参数；不发送该字段也不代表供应商零留存，数据策略单独配置和核实         |

Qwen 3.7 Plus 默认开启混合思考，可显式关闭；这是先采用快速配置的依据，质量与延迟仍需业务评测。[深度思考文档](https://help.aliyun.com/zh/model-studio/deep-thinking)

官方已列出 Qwen3.7-Plus 的 JSON Schema 支持，但各关键字存在限制，例如 `oneOf` 不严格保证仅匹配一个分支。适配器转换 Schema 后仍保留完整的本地 Pydantic 校验及业务校验；不以供应商 strict 标志替代它们。不能静默去掉必要约束或退化为任意文本解析。[结构化输出文档](https://help.aliyun.com/zh/model-studio/qwen-structured-output)

当前 Chat API 支持该系列的 `max_completion_tokens`，而结构化输出文档提醒输出上限会导致截断。coRoof 保留有限预算、完整解析与截断失败处理；上线门槛包含“结构化模式 + 有限输出”的真实联调，不能因追求完整 JSON 去掉费用上限。各端点支持组合单独验证。[Chat API 参数](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)

JSON Object 只可作为另外登记且通过同一评测的配置，不在某次 400 后自动探测或降级启用。新增其他模型时复用相同业务契约，分别补充参数映射、协议解析、能力证据和评测记录。

## 预算、错误与降级

首期依据问答保持一次模型请求、零自动重试；建议初始总期限 25 秒、连接期限 5 秒、模型总输出预算 2,500 tokens、响应解压后最多 150,000 字节，均为 coRoof 初始工程值，不是供应商性能承诺。输入预算由任务与已验证上下文上限共同限制。总期限覆盖排队、连接和完整读取，不能只依赖 httpx 的单次读超时；响应大小在读取过程中限制，不能全部读入内存后才检查。

| 错误                        | 稳定类别                                                  | 首期处理                                         |
| --------------------------- | --------------------------------------------------------- | ------------------------------------------------ |
| 未配置、用途/模型能力不匹配 | `not_configured / policy_denied / unsupported_capability` | 不发请求；问答可用规则，提案停止                 |
| 401/403、无效参数或 Schema  | `authentication / permission / invalid_request`           | 不重试、不切换 Key 或试探端点；给管理员脱敏原因  |
| 429、5xx、连接/读取超时     | `rate_limited / unavailable / timeout`                    | 记录失败并按任务降级；未来重试显式消耗剩余总预算 |
| 拒绝、截断、超大响应        | `refused / truncated / response_too_large`                | 不采信部分输出，不尝试修复成答案                 |
| JSON/Schema/引用/提案不合法 | `invalid_output / invalid_evidence / invalid_proposal`    | 保留原因码，不能放宽业务校验换取通过             |
| 用户取消、预算耗尽          | `cancelled / budget_exceeded`                             | 停止后续调用和执行，不呈现为成功                 |

预算在租户和当前任务范围分别限制并发、调用次数、token 和费用；未来 Harness 每一步共享剩余总预算，不能每轮重新获得完整额度。具体 Agent 步数在任务循环设计中设定，默认没有无限循环。

不承诺超时/取消会撤销供应商已产生的账单。价格缺失、超时无 usage 或供应商未报告时记 unknown，不能记为零；需要严格费用上限的路由在无法估算时不得启动。能够估算时按输入、输出上限、计价版本和供应商允许误差预留，完成后按实际用量结算。恢复前一次结果未知的调用不能假定未发送；避免自动重复请求导致额外费用。

规则由业务层提供，并与模型结果分开标记。UI 保留“规则整理 · 非 AI”，区分未配置、主动规则模式与模型失败降级；备用模型若未来启用，应记录实际模型及尝试链。任何降级都不能直接改变事项或跳过明确确认。

## 配置、审计与数据库演进

配置分三组：部署保存端点与 credential_ref；ModelProfile 保存模型能力和参数；TaskPolicy 保存任务路由及预算。非敏感配置随代码版本化；密钥用 SecretStr/环境注入。启动时离线检查引用、用途、URL、能力和预算，不自动发测试请求；连通性探测是显式操作并计入额度。

保持 HTTPS、无 URL 内凭据/查询参数、无重定向和 `trust_env=false`；本机 HTTP 仅用于开发测试。后端默认拒绝已知 Coding Plan 端点及对应套餐凭据类型的错误配置，仅按上述单连接本机测试条件开放，不用字符串前缀替代完整配置与身份校验。查询请求不接受 base_url、model_id、API Key 或供应商参数覆盖；企业连接只能通过 Owner 专用管理接口保存。

拟增加 `ModelInvocation` 记录：organization_id、actor_id、analysis_run_id、request_id/attempt、task/profile/adapter/prompt/schema 版本、请求与返回模型标识、provider_request_id、开始/完成时间、状态/错误码、token usage、费用估计及其来源。关联 AnalysisRun/Membership 使用租户复合外键，幂等标识至少限定企业、主体、任务与请求；同标识不同输入指纹冲突。请求指纹不替代对象权限或原始数据留存策略。

AnalysisRun 仍保存一次业务分析及最终经校验结果；ModelInvocation 保存其模型尝试，不把降级后的规则答案记成模型成功。网络前以短事务记录 pending 调用并释放锁，网络后用短事务记录结果；进程中断留下的 pending 标为 unknown 并受控恢复，不自动重放。技术调用记录不是 WorkEvent；业务写入仍由已有领域服务在单一事务追加事件和更新投影。

新增表和必要字段使用下一条 Alembic 追加迁移。旧记录保持原义：没有真实用量的历史模型调用为 unknown，确定性规则成本为零，不回填虚构调用记录。审计不保存 Key、Authorization、隐藏推理、完整提示或未过滤供应商报错。业务证据仍沿用受权限保护的现有快照。

## 实施顺序与验收

建议新增 `backend/app/modules/model_gateway/`，包含 contracts、gateway、profiles、routing、errors 和 adapters；业务提示及引用校验继续留在 intelligence。具体文件粒度随实现确定。

1. **A：抽离统一入口。** 保留现有默认规则模式和公开 DTO，迁移现有问答适配器；补充版本化配置、严格内部契约、错误分类和调用记录。验证原 Slice 01–02 行为不变。
2. **B：百炼 Qwen 配置。** 完成端点与参数适配、Schema 检查、期限/预算和脱敏测试。使用允许后端用途的通用 API、明确标注的合成数据完成真实联调后，才允许显式启用模型路由。
3. **C：接入 Agent。** 在能力注册表、提案授权执行器和持久化循环就绪后，把提案路径接到 Gateway；先启用既定四项读取能力。草稿与确认仍按 Agent 文档逐项验收。
4. **D：基于评测增加模型。** 第二个具体模型由实际成本/质量需求决定；为每个组合补充 Profile 与必要 Adapter，不提前宣称支持任意兼容模型。

共同验收要求：

- 同一组中文合成业务案例覆盖缺数据、陈旧记录、来源冲突、越权引用、提示注入、格式错误、拒绝、截断和取消；正确结构不代表正确事实，分别报告。
- 两个租户、Owner/Manager/Member、调用中途撤权、历史读取和缓存/恢复验证隔离；任何非法提案不触发工具或业务写入。
- 每个 Profile 验证实际请求字段、Schema、finish_reason、usage 缺失和脱敏；网络故障用 MockTransport 覆盖，在线联调记录具体端点地域、模型和版本，不使用生产客户资料。
- 模型优化对比结构通过率、引用通过率、人工判断的建议质量、拒绝/降级率、端到端 P50/P95、实际 token 与费用；用同一数据集对比默认/优化配置。先固定业务正确性，再比较速度和费用，不以调用成功率替代质量。
- 重复请求、预算并发扣减、故障恢复和追加迁移在 PostgreSQL 验收；业务确认保持作者、版本、幂等与事务约束。
- 运行 `docs/v1-development.md` 中 Python Ruff/format/mypy/pytest、Web 格式/类型/交互/构建及 Go 检查；公开契约改变时重新生成并核对 API client。

启用状态以交付记录的实际验收为准。真实模型可用也不解除生产环境对真实身份、投递和部署控制的阻断。
