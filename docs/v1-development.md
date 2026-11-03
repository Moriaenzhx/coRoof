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
uv run python ../scripts/acceptance.py --base-url http://localhost:3000
```

`acceptance.py` 只接受 development/test + mock；创建一组唯一命名的本地合成数据并输出测试邮箱、企业与事项 ID。使用测试邮箱重新获取开发验证链接即可查看；不输出会话/邀请令牌。

## 浏览器手工验收

1. 创建开发身份并建立企业；组织与工作 → 部门，建立销售、研发、交付。
2. 创建公司级项目；邀请交付员工，复制开发邀请链接。
3. 员工在另一浏览器会话用受邀邮箱验证身份，打开链接并接受。
4. 老板刷新成员列表，创建事项并指定该员工及项目。
5. 员工进入我的工作，在事项详情输入“客户资料晚到两天，需要交付协调”。生成后检查原文、规则标记和可编辑建议，确认前老板状态不改变。
6. 员工确认，老板刷新全景，查看负责人、支持需求、原文与证据 ID。销售/研发保持未知。
7. 网络重试同一确认只返回原事件；其他员工或另一企业的身份读不到该事项。需要支持与生命周期独立。

## 部署前置条件

本轮的 mock 可以模拟任意邮箱，绝不能用于公开服务或真实员工身份认证。production 启动被拒绝。下一步正式部署前需实现真实身份 Provider 与邮件发送器，配置 HTTPS/secure cookie、限流、密钥及凭据管理、备份恢复、审计保留和授权验收。真实 LLM / 飞书 / GitLab 凭据尚不需要，也没有寻找或配置。
