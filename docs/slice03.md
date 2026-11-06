# Slice 03 / 阶段 4：只读外部连接器

2026-11-04：按用户要求先完成离线实现。GitLab / 飞书项目的真实测试项目尚未提供；离线验收不代表账号权限、真实字段或线上稳定性已验证。Native 工作、原 Go Runtime 和共享协议继续独立。

## 业务路径

企业所有者从账户菜单进入“外部连接”，选择 GitLab 项目数字 ID 或飞书项目空间/工作项类型、归属部门和只读凭据，明确确认数据分享范围。保存仅加密入库；连接测试成功后另行启用，再主动发起全量同步。Owner、对应部门负责人和被分配成员按既有事项权限查看结果。普通成员不能读取连接配置或未映射的来源。

同步先保存不可变 SourceRecord，再更新稳定 SourceLink。没有明确状态映射、负责人字段未知、成员未绑定/失效或多负责人时保持待映射，不猜测状态/身份、不创建虚构事项。Owner 手工对应外部状态和当前部门有效成员后重新全量同步；飞书负责人字段 Key 可修正。来源中的名称或邮箱不会用于模型自动匹配。

外部来源有权维护自己的事项投影；同步事务中同时追加 WorkEvent、更新投影/信号并记审计。成员不能在 coRoof 编辑外部事项。截止时间与支持需求暂不导入，页面和模型上下文明确为未知；不能由 opened 或没有支持标记推断健康。更新时间采用源记录时间，独立保留最近读取时间。说明性决策仍保留人的明确确认，不回写外部项目。

## 框架与协议

GitLab 使用 [python-gitlab 8.6.0](https://python-gitlab.readthedocs.io/en/stable/api-usage.html) 的 project/issues 资源和 HTTP 错误处理；应用薄层限制只读 GET、单页、超时、大小与固定项目范围，不重复实现 SDK。使用 read_api 权限并限制可读项目，保存前应确认授权可向本企业分享该范围。

飞书使用**飞书项目** OpenAPI，而非普通飞书消息/文档 API。当前 Python 服务以 HTTPX 薄适配 plugin_token 和 work_item/filter；契约核对自官方 [project-oapi-sdk-java](https://github.com/larksuite/project-oapi-sdk-java)，查阅版本 `03a3a7fad63560a71416d1552f8d24936a98b47e`。未引入额外 Java 服务或伪称普通飞书 SDK 可替代。真实租户中的工作项类型、负责人字段 Key、状态 Key、插件/用户授权仍需联调。飞书来源 URL 未获得可靠契约时不编造跳转地址。

固定允许 `https://gitlab.com` 和 `https://project.feishu.cn`；自建 HTTPS 源需部署管理员配置 `COROOF_CONNECTOR_ALLOWED_BASE_URLS`。不接受任意租户请求地址、URL 凭据或重定向。限制单个响应 2 MB、请求超时 15 秒、单页 50 条、单次 100 页及 30 分钟。飞书的 POST 是这两个固定鉴权/只读查询接口，不是外部写入工具。没有 webhook、自动发现全部组织项目或外部写操作。

## 持久化、恢复与授权

Alembic `0008_connectors` 新增 Connector、SyncRun、SourceRecord、SourceLink、SourceMember、SyncOutbox。租户所有的关联均带复合租户外键；SourceLink 同时绑定同租户同连接的 SourceRecord。原始 JSON 与标准化结果不可变，去重摘要包含两者，允许修正标准化配置后保留旧快照。连接凭据复用部署 Fernet 加密密钥，密文绑定用途、企业和连接 ID；接口只返回末四位，无密钥回显。

连接范围在创建时明确，暂停/撤销隐藏其外部事项；撤销同时删除密文并取消待执行任务。更新凭据回到待测试状态。读权限由当前服务器 Membership 与活动 SourceLink/Connector 联合决定，列表、详情、证据、Agent、决策及结果读取都重新授权。每次 Worker 读取前后重新检查当前 Owner 身份和连接版本；中途撤权/改配置时丢弃返回内容。

Celery + Redis 执行有界单页任务，Beat 每十秒投递数据库 Outbox。每页 intake、事件/投影、下一页消息在同一 PostgreSQL 事务中完成。消息重复投递通过运行版本与状态实现一次效果；broker 故障保留消息，确认未知允许重复投递。Worker 读请求不持有长数据库事务；90 秒租约过期重派，旧 Worker 结果被版本隔离。复用 Tenacity 计算 2–60 秒指数退避，429/网络/5xx 每页最多五次；凭据失败/格式不符不盲目重试。错误码脱敏，不存原始异常或凭据。

全量扫描限定开始时的时间窗；分页中未见的旧条目另行单项核对，避免并发更新/分页移位造成误删。仍不可读/已删除的条目隐藏，原始记录保留。增量从上次成功时间窗前一分钟开始，容忍重叠，忽略比当前来源更旧的结果；成功前不推进水位。增量不发现删除，需定期全量核对。失败可已完成部分页，页面明确覆盖与错误，不声称完整同步。

coRoof 内暂停/撤销即时影响服务端读取；源平台发生的授权变化要在下一次测试/同步中才能发现，当前不是实时远程 ACL 镜像。单项删除/撤回需要全量核对。持续 Agent 启用前必须增加来源新鲜度门槛与策略驱动的周期核对，不能把历史同步成功当作永久授权或最新事实。

当前由 Owner 手动启动全量/增量任务，Beat 只负责可靠投递与恢复；尚未自动定期抓取项目。后续持续 Agent 的策略与有依据的自主规划按 [持续 Agent 设计](continuous-agent.md) 实施，不能将连接器 Worker 等同于已运行的企业自主 Agent。

## 离线验收

`backend/tests/test_connectors.py` 使用真实 python-gitlab 客户端配合 responses、HTTPX MockTransport，以及实际 Alembic/PostgreSQL 事务。覆盖分页/时间窗、错误/超限/范围拒绝、加密/角色/租户外键、显式启用、待映射/人工绑定、重复/乱序、来源权威、全量单项核对、撤权与派生证据/决策不可见、网络退避、Outbox broker 故障/重复投递、租约恢复、并发 Worker 和旧库迁移保留。Web 交互测试覆盖保存不自动测试、测试后单独启用、人工映射、撤销确认、冲突与外部只读来源。

```sh
cd backend
COROOF_TEST_DATABASE_URL='postgresql+psycopg:///coroof_v1_test_1103?host=/tmp' .venv/bin/pytest tests/test_connectors.py -q
```

真实联调待用户提供测试范围后，逐平台检查连接/授权、实际分页与增量、字段/成员映射、项目/单项撤权、重试和源链接。不发送现有业务数据给测试平台，不把测试 fixture 放入真实企业。后台启动需同时运行 API、Worker 与一个 Beat 调度进程，环境中使用同一加密配置和数据库。正式部署仍由阶段 7–8 的身份、投递、部署与团队试点门槛控制。
