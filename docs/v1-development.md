# V1 开发与验收

## 环境与一条命令启动

首选 Docker Engine + Compose v2+：在根目录执行 `sh scripts/dev.sh`。Compose 包含 Postgres 16、Redis 7、migrate、API、Worker、Next.js Web。需要足够磁盘空间拉取镜像和构建（建议至少 5 GB）。只监听回环地址，不创建生产部署。

Web 为 `http://localhost:3000`，API 为 `http://localhost:8000/docs`。停止本地容器使用 `docker compose -f infra/compose.yaml down`；不要加 `-v`，以免删除数据卷。修改环境变量时显式 `--env-file`。密码中的 URL 保留字符应正确编码。

## 原生进程路径（Docker 不可用时）

要求 Node 22.12+、uv、正在运行的 PostgreSQL 16+、redis-server。不改变已有数据库，创建专用开发/测试库：

```sh
createdb coroof_dev
createdb coroof_test
export COROOF_DATABASE_URL='postgresql+psycopg:///coroof_dev'
export COROOF_TEST_DATABASE_URL='postgresql+psycopg:///coroof_test'
export COROOF_REDIS_URL='redis://127.0.0.1:56379/0'
export COROOF_WEB_ORIGIN='http://localhost:3000'
npm ci
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run alembic check
uv run uvicorn app.main:app --host 127.0.0.1 --no-access-log
```

在另外的终端启动（保留上述环境变量）：

```sh
redis-server --bind 127.0.0.1 --port 56379 --save '' --appendonly no
# 从 backend/ 启动；macOS 本地验收可使用 solo，Compose 使用 prefork。
uv run celery -A worker.app:celery worker --pool=solo --loglevel=WARNING
# 新开终端，从 backend/ 启动调度器，连接器 Outbox 每十秒投递
uv run celery -A worker.app:celery beat --loglevel=WARNING --schedule=/tmp/coroof-beat
# 从仓库根目录启动
npm run dev
```

浏览器统一使用 `http://localhost:3000`，与 `COROOF_WEB_ORIGIN` 完全一致。不要混用 localhost / 127.0.0.1 导致 Origin 校验失败。Node 的服务地址虽显示 127.0.0.1，localhost 同样连接该进程。

本次机器的原生验收使用独立库 `coroof_v1_dev_1103`、`coroof_v1_test_1103`，Unix socket `/tmp`。前者保留明确命名的验收示例供本地查看。测试为每个案例创建随机独立 schema 并在结束后清理，仅接受名称包含 test 的数据库，绝不对现有业务库重建。

也可在配置专用 `COROOF_DATABASE_URL` 后，从根目录运行 `sh scripts/native-dev.sh`，统一启动 Web / API / Worker / Redis；退出时只停止其子进程。`COROOF_UV`、`COROOF_REDIS_BIN` 可指定工具路径；若复用已运行的 Redis，显式设置 `COROOF_REDIS_BIN=''` 并提供 `COROOF_REDIS_URL`。日志位于忽略目录 `.local/`。

## 检查

```sh
cd backend
uv sync --frozen
uv run ruff check app worker tests migrations ../scripts
uv run ruff format --check app worker tests migrations ../scripts
uv run mypy app worker
uv run pytest -q
uv run python ../scripts/export_openapi.py
cd ..
npm ci
npm run api:generate
npm run format:check
npm run typecheck
npm test
npm run build
go vet ./...
go test -race ./...
go build ./cmd/coroof
```

`sh scripts/check.sh` 合并上述步骤。未配置 `COROOF_TEST_DATABASE_URL` 时测试使用临时 SQLite，PostgreSQL 行锁并发测试明确跳过；正式验收和 CI 必须配置 PostgreSQL 测试库。API 类型生成后运行 `git diff --exit-code -- packages/api-client` 检查生成漂移（初次新增文件应先检查生成内容）。

Worker 真实排队验证：

```sh
cd backend
uv run python -c 'from worker.app import ping; assert ping.delay().get(timeout=10) == "pong"'
uv run python ../scripts/acceptance.py --base-url http://localhost:3000 --slice02
```

`acceptance.py` 只接受 development/test + mock；创建一组唯一命名的本地合成数据并输出测试邮箱、企业与事项 ID。使用测试邮箱重新获取开发验证链接即可查看；不输出会话/邀请令牌。

## 浏览器手工验收

1. 创建开发身份并建立企业；在“团队”页点击“组织与工作” → 部门，建立销售、研发、交付。
2. 创建公司级项目；邀请交付员工，复制开发邀请链接。
3. 员工在另一浏览器会话用受邀邮箱验证身份，打开链接并接受。
4. 老板刷新成员列表，创建事项并指定该员工及项目。
5. 员工进入“我的工作 → 工作清单”，通过状态筛选或搜索定位事项，点击“汇报进展”或“需要支持”。抽屉打开后聚焦空白输入框；输入“客户资料晚到两天，需要交付协调”，生成后检查原文、规则标记和可编辑建议，确认前老板状态不改变。
6. 员工确认，老板在首页“需要留意的事项”和项目速览中核对更新，进入事项查看负责人、支持需求、原文与证据 ID；需要组织范围时再点击“展开全景”。未记录工作的销售/研发保持未知。
7. 网络重试同一确认只返回原事件；其他员工或另一企业的身份读不到该事项。需要支持与生命周期独立。

8. 老板在底部输入框发送问题，或从事项“询问这项工作”带入上下文后发送，在居中浮层查看处理状态与原始依据。切页后可展开继续查看；模型配置不可用时显示失败说明，不把规则结果当作 AI 回答。“我的工作 → 最近查询”可只读回看最近 5 次查询。
9. 点击“准备决策”，明确选择方案并填写跟进；在“我的工作 → 我的决策与跟进”核对本人待办，确认后追加实际结果，重复提交不重复写入。老板也可在“企业概览”展开“企业决策记录”，或在项目详情点击“查看项目决策记录”核对对应范围。
10. 新进展、时间规则变化或超过三十分钟后，旧方案确认应返回冲突提示；重新核对记录后再准备。

## 企业 AI 管理验收（阶段 1 增补）

配置 `COROOF_AI_SECRET_KEY` 后执行 Alembic `upgrade head`，通过账户菜单进入“企业 AI 设置”。依次检查新增连接、只保存不调用、显式测试、测试通过后再启用、预算冲突刷新、撤销凭据后暂停、操作记录。普通成员仅能看本人用量，部门负责人不自动拥有配置权限。

原生协议分别覆盖 OpenAI、Claude、Gemini，Chat Completions 预设覆盖百炼与 DeepSeek；目录不是已实测的模型清单。自定义与地域端点在 `COROOF_AI_ALLOWED_BASE_URLS` 登记，详见 [AI 管理说明](ai-management.md)。平台服务可在尚未配置模型时保存额度，此时继续明确标记规则模式。金额费用尚未对账，不显示虚构余额。

定向自动验收：`uv run pytest tests/test_ai_management.py -q`，仍需 PostgreSQL 才能验收并发保存。页面交互测试位于 `apps/web/tests/ai-settings.test.tsx`。真实模型调用必须使用对应账号授权且允许应用用途的 API 凭据；开发 Coding Plan 测试不会计入企业业务用量。

## 部署前置条件

默认 mock 可以模拟任意邮箱，绝不能用于公开服务或真实员工身份认证。阶段 7 已提供 Authlib OIDC、SMTP outbox 和独立生产模板；真实服务与发布验收未配置时 production 启动被拒绝。标准接入、限流、备份恢复与停机说明见 [身份与部署](identity-deployment.md)。真实模型为可选的服务端配置，见 [Slice 02](slice02.md)；默认规则模式无需密钥。飞书 / GitLab 的离线实现已完成，真实项目联调仍待完成。

阶段 4 开发验收与部署边界见 [只读连接器](slice03.md)。Compose 的 Beat 复用 API/Worker 的数据库与加密配置，调度同步投递、恢复和阶段 8 的 [持续关注](continuous-agent.md)。获得老板的有效范围授权后，Agent 可读取事实、提出推进建议与到期跟进；业务变更仍须相关作者明确确认。

阶段 5 文档验收：`uv run pytest tests/test_knowledge.py tests/test_knowledge_agent.py -q`，发布竞争与在途读取/撤权仍需独立 PostgreSQL 测试库。真实合成模型验收复用 `scripts/agent_acceptance.py --knowledge --actions --config-file .local/coding-plan-test.json --database-url <独立测试库> --report .local/knowledge-live-acceptance.json`，最多 37 次模型调用，无自动重试；不能使用真实企业文档。页面从主导航“企业知识库”进入。当前 0009 迁移与验收记录见 [知识库](knowledge.md) 和 [顺序交付](v1-delivery.md)。


阶段 6 验收：`uv run pytest tests/test_memory.py -q`，并发用例需要 PostgreSQL。真实合成模型命令在上述知识验收基础上追加 `--memory`，需要 `--actions`，最多 51 次模型调用且无自动重试；参见 [决策记忆](decision-memory.md)。该阶段 Alembic head 为 `0010_memory`；当前为阶段 8 的 `0016_attention`。

阶段 8 当前迁移为 `0016_attention`。定向验收：`uv run pytest tests/test_watch_controls.py tests/test_watch_queue.py tests/test_watch_agent.py tests/test_watch_runner.py tests/test_watch_attention.py -q`。设置 `COROOF_TEST_DATABASE_URL` 指向专用 PostgreSQL 测试库；额外设置 `COROOF_TEST_REDIS_URL` 后运行 `tests/test_watch_broker.py`，将启动两个独立 Worker 生命周期并只清理本次唯一测试队列。

真实开发模型：`backend/.venv/bin/python scripts/watch_acceptance.py --config-file .local/coding-plan-test.json --database-url <专用 PostgreSQL 测试库> --report .local/watch-live-acceptance.json`。最多两轮图/十二次调用，不自动重试，使用随机隔离 schema 的合成事实，不读取企业模型连接或应用环境密钥；通过后仍不代表通用 MaaS 商用业务入口验收。

关注 Worker 每十秒合并事务唤醒、补偿到期策略和投递任务。每轮最多一百项覆盖、一个事项分析；额度按滚动二十四小时保守预留，未知调用不盲目重发。已完成图步骤可恢复而不重复请求；分析仍受企业调用/Token/并发上限。成功同步的时间戳不引发重新计费；外部来源超过二十四小时未成功核对时按资料缺口处理。Worker 停止窗口为一百八十秒，容纳有界模型步骤；生产发布仍需真实身份/投递/域名与试点门槛。

完整模拟经营验收见 [星桥软件多角色案例](enterprise-rehearsal.md)。`tests/test_enterprise_scenario.py` 与 `scripts/enterprise_scenario.py` 复用同一套公开 API 场景；网页演练保留带“模拟”标记的数据，隔离数据库测试仅清理自身随机 schema。真实开发模型另走显式配置的 `scripts/enterprise_model_acceptance.py`，每轮最多 19 次调用，不启用应用后端的 Coding Plan 入口。

## 体验优化首轮验收

- 全景及工作概览在页面可见、网络在线时每三十秒读取实际记录；详情打开、提交期间及配置或知识库编辑页面暂停自动刷新。部门预览、更新时间与状态均来自已授权数据，缺失信息保持未知。
- Companion 明确显示“按已记录工作整理 · 未调用模型”；建议入口仅预填问题，由用户发送后才开始查询。
- 团队动态读取当前授权范围内最近六项工作，每项最多三条事件，合并展示最近六条，并显示事件操作者；这是部分工作记录，不代表完整企业活动流。
- 项目视图支持筛选、展开工作明细及进入事项，展示实际负责人、期限、支持需求与生命周期分布。
- coRoof 头像与部门卡片提供有限的状态反馈；按钮、详情及卡片支持键盘焦点，并遵循系统减弱动效设置，不用持续动画暗示后台智能体正在运行。

本轮自动检查：Web 交互测试 81 项通过；SQLite 后端测试 281 项通过、20 项跳过；Ruff 检查、格式检查、mypy 及 Go 检查通过。本轮未修改后端 schema 或权限逻辑，未重新运行 PostgreSQL 并发验收；SQLite 结果不能替代该项验收。

2026-11-04 本地 Compose Web 构建并更新成功。浏览器使用“星桥软件”合成企业核对桌面全景、实际团队事件、Agent 问题预填但不自动发送、项目支持事项筛选、事项证据下钻及 Escape 返回保留筛选。390px 手机宽度下，全景与项目页无文档横向溢出；验收后恢复桌面尺寸。本轮没有启用持续关注授权或发起真实模型调用。截图保存在本机忽略目录 `.local/experience-overview.jpg`、`.local/experience-projects.jpg` 和 `.local/experience-mobile.jpg`；自动检查日志为 `.local/experience-web-tests-final.log`、`.local/experience-backend-checks.log` 和 `.local/experience-go-checks.log`。

随后按用户要求增加全景装饰性环绕：桌面不超过六个部门时，卡片沿原椭圆轨道以 180 秒一圈匀速移动，中心及文字保持正向，连线同步。动画仅改变 CSS transform；普通数据刷新保持当前位置，部门集合变化时统一重建轨道以保持相位一致。鼠标进入轨道、键盘聚焦部门或点击“暂停转动”均可暂停，继续时保留相位；减弱动态效果设置关闭动画，窄屏及多部门保留静态网格。该运动不表示 Agent 正在执行任务。

环绕验收：浏览器核对卡片姿态、连线端点、暂停/继续、键盘和指针暂停，以及 390px 静态布局。Web 81 项通过，SQLite 281 项通过、20 项跳过，格式、类型、构建及 Go 检查通过；本轮无数据库或服务端行为变更。日志见 `.local/orbit-web-tests.log`、`.local/orbit-web-docker.log`、`.local/orbit-backend-checks.log`、`.local/orbit-go-checks.log`。

## 标题伙伴与文本入口

企业全局与我的工作将原大伙伴卡替换为小人和轻提示，全景恢复完整宽度。随后移除顶部横栏，首页移除标题与说明，小人默认位于原左上标题区域；命令输入紧邻伙伴，窄屏自动换行。其他页面保留各自标题及同一伙伴输入入口。企业切换与建立新企业移入“账户菜单 → 个人设置”，即使工作数据读取失败也可使用；开发身份标记保留在账户入口与设置中。小人使用原创 SVG，空闲呼吸、眨眼，点击时短暂挥手并回应；这些本地互动不调用模型。重要提示复用已授权工作事实，排除终态和未经确认的外部状态推断；展开后展示负责人、依据及工作入口。暂时收起仅在当前标签会话存储企业、成员与事项版本签名，不缓存事实内容；新版本可以重新提示。

小人支持鼠标和触控拖动，点击与拖动有阈值区分；浮层及小人限制在可用视口内，可以恢复原位、暂停动画或使用系统减弱动效。头像悬停保持透明背景。浮动组件挂在 body，避免 workspace 容器使固定定位偏移；原生详情对话框仍位于其上。普通成功刷新不会重开浮层或重播招呼；读取失败仍清除事实，切换身份范围重置局部状态。

伙伴旁提供文本输入发送框，拖动小人时输入框留在默认位置。明确发送后，使用现有 Agent 只读查询一次；中文输入法确认候选字不会提交，空白禁用，普通事项建议仍只预填。StrictMode、普通重渲染及查询方式切换不重复自动发送。业务变更继续经过原有草稿、作者确认与权限检查，未扩展 Agent 工具权限。

该轮 Web 共 101 项通过，PostgreSQL / Redis / 本机 SMTP 全量 301 项通过、无跳过；Ruff、format、mypy、Go vet/race/build 与 Web 构建通过。浏览器核对桌面/390px 布局、输入启用状态、拖动与点击区分、边缘浮层、恢复原位、透明悬停背景和 Escape 回焦。本轮未新增真实模型调用或后台关注授权。日志见 `.local/header-companion-web-tests.log`、`.local/header-companion-web-build.log`、`.local/header-companion-backend.log`、`.local/header-companion-go.log`。

2026-11-04 伙伴入口布局调整验收：Web 104 项通过，包含设置切企业、未发送指令清空、角色切换、旧在途响应隔离，以及业务读取失败仍能切换企业。Python Ruff/format/mypy 通过；PostgreSQL 全量 300 项通过，显式 Redis 的 Worker 重启投递项单独补测 1 项通过。Go vet/race/build/provider、Web 格式/类型及 Docker 构建通过。本地 Web 已更新，浏览器核对桌面与 390px 布局、输入状态、拖动不误点、恢复原位和设置入口；手机无文档横向溢出。截图为 `.local/companion-dock-overview.jpg`、`.local/companion-dock-settings.jpg`、`.local/companion-dock-mobile.jpg`；日志为 `.local/companion-dock-web-tests.log`、`.local/companion-dock-web-build.log`、`.local/companion-dock-backend.log`、`.local/companion-dock-go.log`。

2026-11-05 输入区调整为圆角多行卡片，桌面最大 560px 宽、默认约 108px 高。输入从两行自动增高至五行，超过后内部滚动；内容删除或发送后恢复高度，容器宽度变化会重新测量。Enter 明确发送、Shift+Enter 换行，保留中文 IME 候选确认保护；手机输入字体 16px。底栏仅提供询问提示、键盘提示和真实发送按钮，继续复用现有只读查询。该轮下方首页信息层级仅作评审，后续实现与验收见下节。

本轮 Web 106 项、PostgreSQL/Redis 全量 301 项通过；格式、类型、Ruff/mypy、Go vet/race/build/provider 及 Docker 构建通过。本地 Web 已更新。浏览器核对桌面、900px 与 390px 布局、Shift+Enter 不发送、六行输入在 120px 内滚动、清空恢复及无横向溢出。截图 `.local/composer-overview.jpg`、`.local/composer-mobile.jpg`；日志 `.local/composer-web-tests.log`、`.local/composer-web-build.log`、`.local/composer-backend.log`、`.local/composer-go.log`。

## 老板与员工工作台（2026-11-05）

当前老板首页主路径为“需要留意的事项 → 项目速览 → 团队动态”，企业全景按需展开。同一事项的支持需求、规则提示与后台关注记录合并呈现，保留依据和各自状态；项目速览可定位到对应项目明细，紧凑团队动态仍只展示当前获授权的实际事件。摘要数量不等于项目整体完成度，未读取或不可见的信息保持未知。

员工的“我的工作 → 工作清单”提供待推进、进行中、未开始、需要支持、已结束筛选，以及工作、项目、部门搜索。卡片随可用宽度排成三列、两列或单列，日期与操作按钮可换行。未结束事项按支持需求、已过记录截止、截止时间排序；已结束事项按记录更新时间排列。“汇报进展”和“需要支持”只打开空白草稿，员工核对并确认后才写入；外部来源和终态事项保持只读。事项问答仅带入本人可见的工作上下文，“与我相关的动态”只读取本人事项事件。

本轮同时修复原生详情对话框打开后的输入框聚焦；退出后重新登录按角色进入全局或我的工作，不保留上一账号的页面。工作已不在快照中时，不回退到无关详情或全局问答。外部来源的支持需求保持未知，负责人资料不可见时不误报为未分配。未修改后端 schema 或扩展业务权限，未新增真实模型调用。

| 检查 | 本轮已完成结果 |
| --- | --- |
| Web | **148 项通过**；格式、TypeScript 和生产构建通过，本机 Web 镜像已更新 |
| Python | Ruff、150 文件格式、mypy 98 源文件通过 |
| PostgreSQL / Redis | **301 项通过、无跳过**；包含并发、租户隔离、明确确认及真实本地 Worker 重启投递 |
| Go | vet、race、构建与离线 Provider 校验通过 |
| 员工桌面浏览器 | 模拟员工陆川生成草稿、核对并保持既有工作状态、本人确认保存，再从“事实与来源”回看记录 |
| 员工响应式浏览器 | 桌面三列、1100px 两列、390px 单列无卡片横向溢出；搜索、筛选及支持入口通过，“汇报进展”进入全屏详情，空白输入框正确获得焦点 |
| 部门负责人浏览器 | 顾岚只见交付部门 3 人、4 项工作，看到陆川刚确认的进展；账户菜单不显示老板配置入口 |
| 老板浏览器 | 林澄看到相同确认记录；核对合并提醒的来源展开、项目直接定位、全景展开收起和财务未知；默认桌面、1024px、390px 无文档横向溢出 |
| 账号切换 | 员工退出后老板直接进入全局，员工登录进入我的工作；全程浏览器未捕获 console error 或 warning |

浏览器验收后恢复默认桌面尺寸和模拟老板首页。截图见 `.local/workspace-v2-owner.jpg`、`.local/workspace-v2-employee.jpg`、`.local/workspace-v2-mobile-report.jpg`。日志见 `.local/workspace-v2-web-tests.log`、`.local/workspace-v2-web-build.log`、`.local/workspace-v2-web-deploy.log`、`.local/workspace-v2-backend.log` 与 `.local/workspace-v2-go.log`。

## 动态全景与底部输入（2026-11-05 后续调整）

按用户后续反馈，企业/部门首页恢复“动态全景 → 需要留意的事项 → 项目速览 → 团队动态”，全景默认展开，仍可收起、暂停转动及从部门下钻。原顶部伙伴与输入占位移除；小人默认右下悬浮、可拖动并恢复原位。桌面输入框固定在工作区底部居中，正文底部随输入框实际高度留白；窄屏小人移至输入上方，提醒气泡和浮层按可见视口夹取，详情仍由原生 dialog 管理。

Mac ⌘K、Windows/Linux Ctrl+K 聚焦输入框，快捷键不提交；输入法组合输入和弹窗打开时不抢焦点。麦克风按钮仅在点击后调用浏览器 SpeechRecognition，中文转写先进入可编辑文本，停止后需明确发送。识别过程不可发送；重复 final 不追加两次，interim 独立显示，拒权/无语音/网络/不支持提供明确反馈。切换身份、切页、禁用、卸载、退到后台以及任意原生或自定义模态窗口打开都会取消识别并拒绝迟到回调，关闭弹窗或返回页面不自动恢复。导航保留当前身份已有草稿，企业/成员切换清空。

语音能力依赖浏览器实现，部分实现会使用在线识别服务；使用前在麦克风说明中提示，coRoof 不创建音频缓冲、上传接口或录音存储。接口行为参考 [SpeechRecognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition)。本轮通过模拟浏览器语音事件验证转写、重复结果、拒权、异常、取消、弹窗竞态与后台中止，**未进行真实麦克风录音或识别服务连通性验收**。

员工知识库入口持续开放，新增当前范围说明。服务端仍按企业共享、本部门、指定成员、本人文档过滤列表/详情；搜索与 Agent 只读取其中已发布版本，其他部门、他人私有、未指定及跨租户内容不可读。新增 HTTP、Agent 和前端矩阵回归，不改变既有授权规则。

验收：Web **180 项通过**，格式、类型、生产构建与本机更新通过；Python Ruff/format/mypy 通过，PostgreSQL/Redis **303 项通过、无跳过**；Go vet/race/build/provider 通过。浏览器核对默认全景、⌘K、多行/不发送、小人拖动/恢复/向上浮层，桌面及 650px、601px、390px 无文档横向溢出，601px 六行输入时按钮仍在卡片内且小人保持在上方。模拟员工陆川可读企业共享的“模拟交付验收制度”第二版并检索原文，文档详情没有编辑入口，弹窗内 ⌘K 不转移焦点。

截图 `.local/dock-voice-owner.jpg`、`.local/dock-voice-mobile.jpg`、`.local/dock-voice-employee-knowledge.jpg`；日志 `.local/dock-voice-web-tests.log`、`.local/dock-voice-web-build.log`、`.local/dock-voice-web-deploy.log`、`.local/dock-voice-backend.log`、`.local/dock-voice-go.log`。

## 导航分组与偏好归位（2026-11-05）

老板主导航按“企业经营 / 知识与经验 / 个人”分组：企业概览、项目与事项、团队、决策与跟进、企业知识库、决策经验、我的工作。部门负责人使用“部门概览 / 项目与事项 / 团队 / 企业知识库 / 我的工作”，概览继续呈现本部门规则提醒；员工以“我的工作”为首个入口并保留授权知识库。未扩展后端角色或数据范围。

当前页采用浅蓝底、深色文字及侧边标记，悬停仅显示浅灰底；图标区分决策跟进与历史经验。分组标题不占键盘焦点，折叠后保留按钮名称和用途提示；手机为横向滚动导航，按钮至少 44px 高，焦点描边置于按钮内避免被滚动区域裁切。企业切换仍在账户菜单的个人设置中。

主导航“决策经验”固定读取 experience；老板个人设置新增“AI 协作偏好”，固定读取当前企业、当前成员的 preference，业务快照读取失败时仍可访问。切换企业或类型重置列表、分页、详情及表单，迟到响应无法恢复旧内容。私人偏好的原有 Owner 权限、候选建立及明确确认流程保持不变，未调用模型或写入业务事实。

验收：Web **190 项通过**，包含角色入口矩阵、独立读取、折叠键盘操作与迟到响应隔离；格式、TypeScript、生产构建和本机更新通过。Python Ruff/format/mypy、PostgreSQL/Redis **303 项**、Go vet/race/build/provider 通过。浏览器以现有模拟老板、部门负责人、员工核对入口、设置、知识库、折叠导航和 390px 横向滚动；无整页横向溢出，未捕获 console error/warning。最后恢复默认桌面尺寸及模拟老板的企业概览。

截图 `.local/navigation-owner.png`、`.local/navigation-manager.png`、`.local/navigation-employee-mobile.png`；日志 `.local/navigation-web-tests.log`、`.local/navigation-web-build.log`、`.local/navigation-web-deploy.log`、`.local/navigation-backend.log`、`.local/navigation-go.log`。

## 决策归入我的工作（2026-11-05）

按用户确认，移除“决策与跟进”一级导航。老板在“我的工作 → 我的决策与跟进”处理本人发起的方案与跟进安排，提供待我处理、待确认、待跟进、已有结果和全部筛选。企业概览显示服务器统计的本人待办数量并链接到我的工作；企业决策记录、展开项目中的项目决策记录按需读取，均复用原 Decision/DecisionOutcome 和详情抽屉。员工与部门负责人保持原权限，不加载老板决策列表。

列表 API 增加 mine、initiative_id、view 和租户内的 outcome_count，过滤后分页；无数据库迁移、额外业务事实或角色扩权。方案确认后进入跟进，实际结果追加后归入已有结果；记录结果不等于解决问题。超过三十分钟的分析提示重新核对，详情可以直接打开只读查询入口；打开入口不调用模型。原人工确认、幂等、版本及来源校验保留。分类、分页、范围切换和刷新拒绝迟到响应，结果读取失败不会显示为零待办。

页面切换回到顶部，横向导航保持当前项可见。浏览器使用已有星桥模拟数据核对了概览到个人待办、已有结果详情、项目内两条关联记录、过期草案的重新核对入口，以及员工三项本人工作和知识库入口；390px 页面无横向溢出，决策按钮至少 44px 高。未新增真实模型调用或修改演练业务数据；验收后恢复默认桌面及模拟老板的我的工作，未捕获 console error/warning。

验收：Web **221 项通过**，最后导航定位调整后 workflow **20 项复验通过**；格式、TypeScript 和 API/Web 生产构建及本机更新通过。后端 Ruff/format/mypy、PostgreSQL/Redis **308 项**及 Go vet/race/build/provider 通过。新增后端覆盖多 Owner 本人归属、项目/租户/来源过滤、分页、未来安排及结果幂等分类；前端覆盖从我的工作确认方案、追加结果后概览和企业历史保持同一记录。

截图 `.local/decision-inbox-owner.png`、`.local/decision-inbox-mobile.png`；日志 `.local/decision-inbox-web-tests.log`、`.local/decision-inbox-integration.log`、`.local/decision-inbox-backend.log`、`.local/decision-inbox-go.log`、`.local/decision-inbox-build.log`、`.local/decision-inbox-web-final-build.log`。

## 居中处理浮层与最近查询（2026-11-05）

工作查询统一通过底部输入框明确发送，事项与伙伴入口仅预填问题和工作上下文。处理进度和结果改为居中的非模态浮层，可手动收起，切页时自动收起，同一企业与身份内保留当前任务及状态；导航不会重新创建或重复推进同一任务。切换企业、身份或角色时隔离旧状态和迟到响应。浮层没有额外问题输入框或“连续查询 / 快速整理”模式控件；证据查看、工作草稿与决策确认仍使用原业务详情抽屉。

“我的工作 → 最近查询”最多显示本人仍获授权的最近 5 次读取任务，不包含后台持续关注。打开历史只读取已有记录，不创建或推进任务，不触发模型调用。交互查询的跨切页保留不等于关闭浏览器后后台继续运行；后台持续关注仍受独立明确授权控制。

本轮复用现有任务读取授权：原登录会话退出或过期、工作上下文或可见范围变化后，旧任务可能不可回看，不是完整的永久查询档案。浏览器实测退出模拟老板再登录后，原会话查询不再列出；本轮没有放宽这项服务端校验。

本轮只读核对现有本机模拟企业：企业 AI 模式为 `disabled`，没有企业连接；平台虽配置供应商和模型名称，可用性预检仍返回 `not_configured`。已有失败任务为 `0/6`，在模型准备阶段停止，未发起模型调用。界面保留真实失败说明，并提供企业 AI 设置或我的工作入口；没有启用模型、添加规则专用接口或扩大权限。真实模型成功路径仍须在可用且已启用的配置下另行验收。

Python Ruff、151 文件格式检查、mypy 98 个源文件通过；PostgreSQL/Redis/本机 SMTP 全量 **308 项通过、无跳过**，Go vet/race/build/provider 通过。已通过日志为 `.local/assistant-overlay-backend.log` 与 `.local/assistant-overlay-go.log`。

浏览器以模拟老板与员工验收了中央结果浮层、无背景遮罩和页面锁定、切页自动收起、未发送草稿保留、本人历史回看、事项仅预填和企业设置入口。员工仅见本人查询，失败时显示联系管理员，不提供企业配置按钮。390px 和 390×500 短视口无文档横向溢出，浮层内容可滚动且不覆盖底部输入；小屏展开浮层时暂隐藏小人与气泡，收起后恢复。未进行真实手机键盘或麦克风验收。

最终 Web **253 项通过**，格式、TypeScript、生产构建与本机更新通过。覆盖跨页保留、重复发送、创建中取消、只读历史、跨企业迟到响应，以及工作区明确返回 401/403 后清除旧答复和未发送草稿；普通网络失败保留任务。后续完整授权刷新成功才重新开放输入，不恢复旧答案或自动重试模型。

日志 `.local/assistant-access-web-tests.log`、`.local/assistant-access-format.log`、`.local/assistant-overlay-final-build.log`、`.local/assistant-overlay-final-deploy.log`；截图 `.local/assistant-overlay-owner.png`、`.local/assistant-overlay-mobile.png`、`.local/assistant-overlay-employee.png`。

### 浮层外观与模型状态说明（2026-11-05 后续调整）

中央处理浮层改为无边框的半透明毛玻璃外观，继续保持非模态、可收起和跨切页保留状态；底部统一输入、本人历史读取以及业务确认抽屉的行为不变。

只读追查确认：原开发用途连接仍已保存，但归属另一企业，尚未完成企业连接测试或启用；当前模拟企业由演练流程暂停模型，平台配置也不完整。保存不等于测试，测试不等于启用，企业之间不自动共享连接。新 Agent 任务对明确暂停返回 `model_disabled`，缺少配置仍为 `not_configured`；旧任务保留原错误码，不将失败改写为成功。此前独立开发测试不赋予业务启用权限，Coding Plan 的当前用途限制见[企业 AI 管理说明](ai-management.md#自助配置与已有凭据可见性)。

本轮未修改企业 AI 设置、连接、凭据或数据库业务数据，未启用任何模型，也未放宽调用策略；只调整浮层呈现与失败原因的区分。

验收：Web **255 项通过**，格式、TypeScript 与生产构建通过；Python Ruff、151 文件格式检查、mypy 98 个源文件及 PostgreSQL/Redis **313 项通过、无跳过**；Go vet/race/build/provider 通过。API、Worker、Scheduler、Web 已更新，本机健康检查通过。浏览器发送新指令确认显示“企业已停用模型服务”，没有发起模型调用；桌面与 390px 验证零边框、16px 背景虚化、无页面锁定、切页收起及展开恢复，小屏无文档横向溢出且不覆盖底部输入。没有捕获浏览器错误或警告。

日志 `.local/model-disabled-backend.log`、`.local/glass-model-web-tests.log`、`.local/glass-model-web-format.log`、`.local/glass-model-web-types.log`、`.local/glass-model-go.log`、`.local/glass-model-build.log`、`.local/glass-model-deploy.log`；截图 `.local/glass-model-owner.png`、`.local/glass-model-mobile.png`。真实模型回答仍待可用的应用用途连接。

### 单连接本机模型测试（2026-11-05 后续授权）

用户明确要求将已保存的百炼测试连接用于当前模拟企业。接入流程由运维明确指定源连接、目标企业和当前有效 Owner，复用服务端导入与加密，原企业连接保持原样；目标连接重新按企业和连接 ID 加密，重复执行保持幂等，追加仅含来源连接 ID 的技术审计，不复制或改写业务事实。连接登记、页面合成测试和明确启用分开进行；旧独立合成验收不能代替新连接测试。

部署新增默认空的 `COROOF_AI_DEVELOPMENT_TEST_CONNECTION_IDS`，本轮仅指定一条目标连接。开发/测试环境、mock 身份模式及当前 mock 成员、回环 `web_origin`、精确供应商/模型/端点和允许名单必须同时成立；例外只用于显式连接测试及前台 Agent 查询。后台持续关注、未列入名单、非本机和生产环境仍关闭，生产预检拒绝带开发名单的配置。界面保留开发用途说明；角色、知识库 ACL、调用预算、幂等及作者确认边界不变。供应商用途限制和本机测试的区别见 [企业 AI 管理](ai-management.md#本轮单连接本机测试例外)。

回退通过现有设置服务暂停目标企业模型，保留连接、审计、额度及业务数据；若当前已改用其他连接则拒绝覆盖。忽略目录中的操作脚本默认只读预览，只有明确参数才执行导入或暂停，不输出密钥、密文或凭据尾号，不自动测试或启用。

本轮已将原加密凭据复制到星桥模拟企业，在浏览器完成连接测试及明确启用 `qwen3.7-plus`。首次业务查询的两轮真实调用成功，但第三轮输入预占 24,928 超过默认 24,000，未发送第三次请求；据已保存上下文离线复现后，仅将获准本机连接的输入上限设为 32,768，保留原预占公式与每日 20 次 / 50,000 Token、每月 100,000 Token 的企业限制。超出新上限仍拒绝，普通连接默认不变。

重新提交“请核对青禾商城一期交付目前需要协调的事项，并根据记录给出下一步建议。”后，实际模型完成 5 轮、使用 12,534 Token，生成客户资料确认及订单接口联调两项建议；两个原始依据入口分别核对到缺商品图片/价格表、缺测试凭据的既有模拟工作记录。切换团队页保留处理结果，“我的工作 → 最近查询”可恢复完成回答，回看不新增模型请求。本轮包含连接测试和首次失败尝试共 8 次供应商调用、16,090 Token，全部实际请求成功；业务 WorkEvent 新增为 0。原企业连接未启用，测试企业保持本机 BYOK 连接启用。

验收：Ruff、152 文件格式检查、mypy 98 个源文件通过；PostgreSQL/Redis 全量 **336 项通过**，后验调用记账修正后 **56 项**定向通过，新增上下文上限回归后相关 **120 项通过**。Web **258 项通过**，格式、TypeScript、生产构建通过；Go vet/race/build/provider 检查通过。API、Worker、Scheduler、Web 已部署到本机，最终 API 健康检查通过。本次未进行通用 MaaS 商用验收，也未启用 Coding Plan 后台持续关注。

日志 `.local/development-connection-backend.log`、`.local/development-connection-final-targeted.log`、`.local/development-context-backend.log`、`.local/development-connection-web-tests.log`、`.local/development-connection-go.log`、`.local/development-connection-final-build.log`；截图 `.local/xingqiao-model-active.png`、`.local/xingqiao-model-answer.png`。


### 老板与员工的简化操作及知识连续问答（2026-11-05）

企业首页改为先看“需要你处理”，同一事项合并、默认最多三项，再看目标/负责人/实际已完成与未完成数，保留动态部门全景。项目明细、证据、自动关注状态、处理记录与团队动态按需展开；全景重新留足节点与中心内容的间距。老板的“我的工作”合并待确认安排和最近查询，没有本人事项时不再展示空工作清单；员工仍以本人事项为主，“汇报进展”直接聚焦输入，历史事实默认收起。

原右侧业务详情也统一为居中原生对话框，按内容高度显示；右侧长表单不再作为默认操作。安排先显示建议和跟进文字，只需核对后点击“确认这个安排”，编辑字段按需展开。过期或依据变化先重新核对；其他人的方案不可代签。没有新增自动确认、通知或工作状态变更。中央查询浮层默认短回答/原文和下一步，过程、其他方案、依据移入一个展开项；切页收起但保留结果，底部只有一个输入框。

知识目录新增 `knowledge.list`，并新增同企业复合父引用迁移 `0017_agent_parent`。前端发送直接上一轮本人成功查询的 `parent_run_id`，可“换个话题”；父记录有原会话、当前权限、当前来源及 24 小时限制，仅带最多 1800 字节的直接父摘要，不递归历史。失效时显式“作为新问题发送”，不自动重试、不挪用旧引用为新事实。

真实模型先后暴露了将目录误当关键词检索、内容追问再次列目录、结构化提案不合契约的问题。最终明确的目录意图和有有效知识上下文的内容追问，复用当前领域授权检索直接返回实际目录或原文，不需要模型选择已经明确的读取动作。答复为 `mode=retrieval`，记录真实 Run/Step/Analysis、`provider=knowledge_retrieval`、`model=none`、零模型调用；保留任务锁、版本、幂等、撤权清理和当前发布版本校验。目录最多 20 篇；正文最多 3 个相关片段、每段 500 字，完整限制可展开查看。风险判断、待确认状态与其他新话题不套用这个目录规则，也不附加旧资料标题。

最终浏览器在星桥模拟企业以老板身份完成“现在企业有哪些知识库”→“里面写了什么？”→《模拟交付验收制度》第二版原文详情，成功显示实际制度文字。两轮分别为 `knowledge.list` 与 `knowledge.search`，父引用正确；随后从“我的工作”回看并切页恢复，无新增模型调用。员工以陆川模拟身份验证仅本人工作、可见企业共享文档、无企业配置入口、简化汇报与 390px 资料详情；窄屏没有横向溢出。未测试真实手机软键盘或麦克风录音，也未提交模拟业务确认来冒充真实执行。

真实经营分析“今天有哪些事需要我处理？”于 17:12 首轮已发送后返回 `unavailable`，尚未执行领域读取；无法根据脱敏记录断言远端 5xx 或具体网络原因。保留未知用量预占，不重放请求、不提高测试限额。最终滚动 24 小时仍为 15 次调用、43,066 Token 计额（已知 23,794，未知预占 19,272），剩余 6,934 不足下一次经营分析预占。该真实经营分析验收仍未通过，不能据目录与原文成功推定任意对话或模型稳定性通过。错误界面已按认证、权限、限流、连接失败等真实错误码说明，失败的安全供应商请求 ID 不再丢失；旧失败记录保留。

Python Ruff、155 文件格式检查、mypy 98 个源文件通过。最终 PostgreSQL/Redis 全量 380 项通过，另一个测试因搜索词与正文恰好重复而误设未命中；修正测试数据后，该项 PostgreSQL 复验通过，共 381 项覆盖。Web 全量 289 项通过，最终精简文案又经 61 项定向、TypeScript、格式复核，生产构建与本机部署通过。Go vet、race、build、provider 检查本轮已通过；数据库已升级到 0017，无数据重置。

## 2026-11-05 Yuxi 对照后的五项改进

完成显式查询的持久执行与三轮受控上下文、BM25Plus 知识排序、已确认安排到成员反馈、主操作精简及统一视觉。完整范围、分阶段门槛、指标和限制见 [五项改进验收](yuxi-improvements.md)。数据库新增 0018/0019，升级前已备份，本机既有企业、事项、事件、决策数量保留；SQLite 非空升级亦有专门回归。

最终全量 PostgreSQL/Redis 431 项、Web 301 项通过；Ruff、168 文件格式、mypy 103 源文件、Web 格式/类型/生产构建、Go vet/race/build/provider 均通过。随后浏览器发现并修复“企业知识库有哪些资料”目录句式，补丁另经 37 项 PostgreSQL 和静态检查。真实桌面、1024px、390px、折叠导航、老板及两位员工视角、知识权限、连续原文查询、切页与刷新后记录核对通过。已部署本机，未提高企业模型预算；真实外部服务与商用发布的待验收项保持。

日志：`.local/simple-final-web.log`、`.local/retrieval-ui-final.log`、`.local/knowledge-retrieval-backend-final.log`、`.local/knowledge-empty-search-pg-retest.log`、`.local/simple-product-retrieval-build.log`、`.local/simple-product-retrieval-deploy.log`、`.local/simple-panorama-spacing-build.log`。脱敏真实验收：`.local/simple-retrieval-live.json`、`.local/owner-question-1712-diagnostic.json`、`.local/owner-question-quota-1719.json`。页面截图：`.local/simple-owner-home.png`、`.local/simple-owner-answer.png`、`.local/simple-employee-update-mobile.png`、`.local/simple-employee-knowledge-mobile.png`。

2026-11-05 后续按用户明确要求，将首页顺序修正为“动态全景 → 需要你处理 → 项目进展 → 折叠的处理记录与团队动态”，企业全景仍位于首页上方。

本次置顶调整验收：Web 289 项、PostgreSQL/Redis 381 项均通过；Web 格式/类型/生产构建、Python Ruff/格式/mypy、Go vet/race/build/provider 均通过。本机 Web 已更新，浏览器确认动态全景位于首屏且在待处理事项和项目进展之前；未调用模型。日志 `.local/panorama-first-web.log`、`.local/panorama-first-backend.log`、`.local/panorama-first-go.log`、`.local/panorama-first-build.log`；截图 `.local/panorama-first-owner.png`。

## 2026-11-06 按角色重排重点、手机导航与资料库

桌面首页仍先呈现企业全景；下方改为“先处理这几件事”，前三项显示顺序、为什么需要关注、负责人、截止时间和一个主动作，其余按需展开。事实来源、后台关注状态放到展开层。员工进入“我的工作”先看真实计数及一项优先工作，按支持需求、记录截止等已有事实排序；其他工作改为分隔列表。手机上反馈安排/汇报进展位于重点标题后，详细安排与时间随后阅读。没有把日期提醒说成实际交付失败，也没有制造审批待办。

手机使用固定底部导航：老板/部门负责人五个入口、员工两个入口，无需横向寻找。企业全景摘要始终在顶部，首次进入手机默认收起部门图，点开可查看；桌面首次进入仍默认展开。输入框空闲时为单行，聚焦或有草稿时展开；点击输入框内部的麦克风/发送不会提前收起。底栏、输入、处理浮层及正文共用实测高度，软键盘出现时隐藏底部导航并按 visualViewport 避让。小人手机提醒为短标签，默认位于输入框上方 12px，保留拖动和恢复原位。

知识库默认“查资料”，只看当前有权阅读的正式内容；“整理资料”集中我的草稿、我创建的和已撤回内容。按真实共享范围分类，不混入上传表单或草稿；单一“添加资料”入口再选择导入/编写，发布与共享设置按需出现。共享分类、发布状态、标题检索在服务端 ACL 后过滤再分页；搜索翻页沿用已提交的关键词和范围，切身份会拒绝迟到响应。正式查阅优先读已发布正文，即使本人另有新草稿也不会误展示。接口说明见 [知识库](knowledge.md)。OpenAPI 客户端已重新生成，本轮无数据库迁移。

统一了表单、选择框、复选/单选、文件选择、折叠说明与按钮的视觉，保留原生语义和键盘焦点。移动主要操作为至少 44px；320px 下操作栏可换行，正文和所有导航均无横向溢出。浏览器实际检查过模拟老板与员工、员工反馈入口（未提交业务变更）、员工只读知识正文、分类/正文搜索、添加资料分步表单、查询后切页并回看结果，以及 320/390/768/1024px 布局。目录查询明确为原文读取，没有调用模型。

验收日志：`.local/product-web-tests-final.log`、`.local/product-workflow-tests.log`、`.local/product-backend.log`、`.local/product-go.log`、`.local/product-web-final-build.log`。Web 最终 328 项、后端 PostgreSQL/Redis 全量 453 项通过，无跳过；Ruff、169 文件格式、mypy 103 个源文件、Web 格式/类型/生产构建、Go vet/race/build/provider 均通过，本机服务已更新。最终截图为 `.local/product-owner-desktop.jpg`、`.local/product-owner-mobile.jpg`、`.local/product-knowledge-desktop.jpg`、`.local/product-knowledge-mobile.jpg`。浏览器响应式验收不等同于真机软键盘或麦克风验收；键盘偏移、视口恢复及输入法/语音生命周期另有模拟事件回归。本机保留星桥模拟数据及既有模型设置，未提高模型限额。


## 2026-11-06 团队入口与工作台

团队页从展开的全员名册改为紧凑的团队入口。首屏展示真实待推进事项、支持需求和有效成员数；进入后在主页面查看工作、切换成员、打开实际关联的项目或现有企业知识库。未归属团队成员与终态工作默认折叠，缺少记录明确保持未知。统一浅色、20px 圆角和列表操作，手机单列且触控区域至少 44px。

沿用服务端部门/事项/成员授权，未新增 API 或数据库迁移，未扩大知识库权限，也没有新增空间级 AI 上下文。页面上的“团队空间”是现有部门的浏览入口；完整空间模型仍见 [统一空间设计](department-data-design.md)。

验收：Web 336 项交互测试、类型与格式检查通过，Next.js Docker 构建通过；后端 PostgreSQL + Redis 453 项通过（0 skipped），Ruff/format/mypy 和 Go vet/race/build 通过。浏览器使用现有明确标识的模拟星桥企业，验证目录、工作/成员切换、真实项目跳转和同一知识库入口；390px 目录及 320px 工作台无横向溢出，团队按钮点击区均不小于 44px。仅更新本机 Web 容器，业务数据和后端服务保留。
