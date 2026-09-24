# Protocol drafts

这些文件是初始化子集，采用 JSON Schema Draft 2020-12。`$id` 是稳定命名标识，目前不承诺对应域名提供在线 Schema 服务；校验器直接加载仓库文件。

- `provider.schema.json`：自描述 Provider Manifest。发现路径约定为 `/.well-known/coroof-provider`；当前 CLI 只做离线文件校验。
- `work-experience.schema.json`：Core 到 Experience Compiler 的工作契约。

## Provider 边界

Provider 通过 Manifest 描述身份、协议版本、资源领域、发现入口、健康入口和认证方案。初始化版本只接受协议 `0.1`；协议版本数组为后续协商预留。

发现入口返回的是定义，不是所有资源实例。认证方案只是声明，不包含密钥，也不授予任何权限。URL 必须是 HTTPS 或根相对路径；CLI 不访问这些 URL。未来远程发现必须加入目标信任、重定向限制与 SSRF 防护。

资源、关系、Capability、Event、Binding、执行结果、错误和健康响应的完整 Schema 仍在设计。OpenAPI / MCP / A2A 适配尚未实现。Provider 的业务内部实现不受 coRoof 语言选择约束。

## 工作契约边界

Core 必须在发出契约前按可信身份、租户和策略过滤事实、证据及动作。Compiler 的 Schema 校验验证结构，不能代替授权。

`actions` 是当前工作状态下的展示快照。UNAVAILABLE 动作应携带原因。Compiler 为 HIGH / CRITICAL 动作保留确认步骤；确认不是权限或审批凭据。任何实际动作都必须回到 Core 重新校验。

样例均为虚构数据。请勿把当前草案当作已冻结标准。

## 维护与许可

共享规范以 Experience Compiler 仓库的 spec/ 为发布源，Core 保留同版本快照。修改需同步两个仓库，并通过跨仓库集成测试。此目录协议资料采用 Apache-2.0。
