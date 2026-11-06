# 阶段 7：真实身份、邀请投递与部署

用户已确认暂时没有身份服务、邮件服务和部署域名，先完成标准接口与本地验收。真实身份服务、收件箱投递和生产部署单独记录，不以本地协议服务或 mock 身份冒充。阶段 6 已通过后进入本阶段；第 8 阶段仍须等待本阶段开发门槛通过。

登录使用 Authlib 的 Starlette OIDC 客户端，复用授权码 + PKCE、state/nonce、发现文档、JWKS 签名与 claims 校验；只使用部署方配置的可信 issuer，拒绝 unsigned/对称签名、未验证邮箱、issuer/audience/nonce/有效期不匹配。部署方配置单一可信登录服务，不从用户输入拼接 token 端点。应用仅保存 issuer + subject 身份绑定及本地会话，不持久化 IdP access/refresh/ID token，不从 IdP roles/groups 推导企业权限。

Authlib 临时 state 放入 Starlette 签名、HttpOnly、Lax、短期 cookie；数据库保存一次性尝试摘要和配置指纹，回调仅可消费一次，配置改变后旧尝试失效。应用会话独立随机令牌，仅保存摘要，Secure/HttpOnly/SameSite Strict；重新登录轮换本次浏览器旧会话，支持退出全部会话。mock 端点只在显式开发模式可用，真实模式拒绝开发会话。现有 mock 用户、企业和角色不自动迁移到同邮箱真实账号；必须显式核验迁移，防止冒领。

邀请继续经过服务端部门/角色授权，采用 python email + aiosmtplib 发送标准 SMTP；凭据从部署秘密注入，生产强制 TLS 验证。邀请与加密待投递记录同事务，Celery/Beat 负责投递、有限退避与中断状态；稳定 Message-ID，SMTP 接受只表示已提交邮件服务，不声称进入收件箱。响应不返回正式邀请令牌，页面显示队列/接受/失败/未知状态。撤销、过期、发起者失权后禁止后续投递；消费邀请仍需匹配已经验证的邮箱，不能自动升级已有成员。

认证和邀请限流复用 limits + Redis，不自行写限流算法；生产 Redis 失效时拒绝敏感入口。身份回调仅接受配置中的固定同源 callback，不接受任意 return URL。浏览器通过同源代理访问，应用不信任客户端角色与转发 IP。部署入口提供 TLS、持久化数据库/队列、独立迁移、健康检查、备份恢复和停机说明；未知外部配置不自动设为已验证。

门槛依次为：OIDC 协议/会话/隔离测试 → SMTP/队列/重试/撤权测试 → 页面真实/开发身份分流 → PostgreSQL 并发与升级 → 部署预检/备份恢复/重启测试 → 全栈回归及本地预览。真实服务与团队试点仍作为发布前外部验收项。

框架依据：[Authlib Starlette OIDC](https://docs.authlib.org/en/v1.5.2/client/starlette.html)、[Authlib PKCE](https://docs.authlib.org/en/v1.5.2/client/frameworks.html)、[limits](https://limits.readthedocs.io/en/stable/quickstart.html)、[aiosmtplib](https://aiosmtplib.readthedocs.io/en/stable/usage.html)。具体实现以仓库锁定依赖的代码与测试为准。

## 配置与身份切换

开发 Compose 保持 `mock`，不改变现有用户和企业数据。正式接口使用 `COROOF_AUTH_MODE=oidc`、可信 issuer、client id/secret、独立签名密钥及固定 `COROOF_WEB_ORIGIN`。在 IdP 注册唯一回调 `https://你的域名/api/v1/auth/oidc/callback`，启用授权码、PKCE S256、openid/profile/email，以及真实的 email_verified。跨主机发现端点须显式加入 `COROOF_OIDC_ALLOWED_HOSTS`。不同 issuer 的旧会话失效；同邮箱 mock 账户拒绝自动绑定，迁移必须单独核验，生产不能承接开发角色。

邀请使用 `COROOF_DELIVERY_MODE=smtp`、SMTP 主机/端口/用户名/密码/发件人以及 `COROOF_MAIL_SECRET_KEY`（Fernet）。TLS 使用 starttls 或 tls，验证服务端证书；明文仅限 test 环境回环 SMTP 夹具。邀请与 outbox 同事务，正式创建必须带幂等键，重复请求返回同一邀请和最新投递状态；只在首次开发模拟响应中返回测试链接。SMTP 前再次校验邀请人当前权限。已经进入发送阶段无法保证撤回邮件，但撤销链接立即阻止加入。

连接建立失败或明确 4xx 拒收最多尝试三次；DATA 后断线或 Worker 中断标记 unknown，必须由管理员核对收件箱并明确确认重试。接受后清除密文；撤销/过期/使用的残留密文由调度器有界清理。成功 DATA 后的 QUIT 失败不会触发重发。生产只运行一个 Beat，Worker 可按容量扩展；重复消息和过期消息由版本与数据库行锁隔离。

登录/回调默认每来源地址 10 次/分钟，邀请每企业成员 20 次/小时，使用共享 Redis。应用不采信任意 X-Forwarded-For；代理部署默认按最后可信连接地址聚合，需按团队并发调整额度。限流服务不可用时敏感入口返回 503。退出所有设备只撤销 coRoof 会话，不声称退出外部 IdP。

## 服务器模板与发布边界

`infra/compose.production.yaml` 是独立模板，不能与开发 Compose 合并。它仅发布 Caddy 的 80/443，数据库、队列、API、Web 不直接发布宿主端口；包含 TLS 自动管理、持久化 PostgreSQL/Redis、独立迁移、进程重启、健康检查和有界日志。Caddy 证书目录独立持久化，禁止记录带授权码的访问 URL。标准模板参考 [Caddy 自动 HTTPS](https://caddyserver.com/docs/automatic-https)。尚未配置真实 DNS 或公开部署。

将 `infra/server.env.example` 复制到仓库外的私有文件并设置 0600；使用部署密钥管理器或受限文件填入实际参数。数据库/Redis 密码建议独立随机十六进制串，连接 URL 中保留字符需要编码。数据库备份、AI 加密密钥、邮件加密密钥和 OIDC 签名密钥须分别备份；丢失 AI 密钥无法恢复已有 BYOK。不要执行会输出配置明文的 `docker compose config`，检查用 `config --quiet`。

```sh
backend/.venv/bin/python scripts/deployment_preflight.py --env-file /absolute/private/server.env
docker compose --env-file /absolute/private/server.env -f infra/compose.production.yaml config --quiet
```

预检仅检查显式文件，不借用本机模型/身份配置；预检与备份脚本不展开 `${变量}`，须在私有文件中填写完整值。只输出缺失项名称，不打印凭据、不连接外部服务。API 和 Worker 在 production 模式再次校验真实身份、投递、HTTPS、cookie、加密与数据库/队列凭据。`COROOF_PRODUCTION_RELEASE_VERIFIED` 默认 false，须完成实际 IdP 登录、受邀邮箱收件、租户访问检查、备份恢复和服务器检查后才能由部署方设为 true；配置检查通过本身不证明外部验收完成。当前离线验收不修改此标记，也未迁移开发身份。

验收与备份完成后，部署方才在目标服务器执行同一 Compose 的 `up --build -d --wait`。只应有一个 scheduler；停止先停 scheduler，再停止 Worker（允许 180 秒收尾，覆盖最长 160 秒的关注任务），最后停 API/Web。中断的邮件按 unknown 核对，未领取的消息按 outbox 恢复。恢复前暂停所有写入和调度，不能让旧 Worker 继续连接恢复目标。不要使用 `down -v`。

## 备份与恢复

复用 PostgreSQL 官方 `pg_dump` custom 格式和 [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html)，不维护自定义数据序列化。`scripts/database_backup.py` 使用显式私有 env 中的数据库连接，密码不进入命令行或报告，文件以 0600 原子创建，已有备份不会被覆盖。备份需由运维复制到加密的异地存储，并制定保留期；数据库备份本身不包含部署秘密和 Caddy 证书。

```sh
backend/.venv/bin/python scripts/database_backup.py backup \
  --env-file /absolute/private/source.env --archive /absolute/backups/coroof.dump
backend/.venv/bin/python scripts/database_backup.py restore \
  --env-file /absolute/private/empty-restore-target.env --archive /absolute/backups/coroof.dump
```

恢复目标必须是已创建且没有业务对象的独立空库；脚本拒绝非空库，不执行 drop/create/clean，使用单事务和遇错即停。凭据只通过子进程环境传给原生 PostgreSQL 工具。容器内主机名在宿主机不可解析时，应在可达数据库的受控运维环境运行，并保持客户端主版本与数据库兼容。只恢复可信来源的备份。

本地验收覆盖 0010→0011 迁移保留原记录、Alembic 无漂移、真实 pg_dump/pg_restore、恢复后记录核对及拒绝覆盖非空库。它不证明异地灾难恢复时长、真实服务可用性或生产容量。
