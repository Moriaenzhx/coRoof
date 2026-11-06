# Roadmap

当前执行计划见 [V1.0 顺序交付与验收](v1-delivery.md)：按用户要求依次实施八阶段，每阶段验收通过后进入下一阶段；真实外部验收缺失不得以模拟通过代替。

当前 V1 按任务书纵向推进：Phase 0 工程基线 → Slice 01 Native 组织工作闭环 → Slice 02 可信风险/证据/决策 → Slice 03 只读连接器 → Slice 04 可撤销决策记忆。后续范围见 [extensions.md](extensions.md)。以下为最初 Go Runtime 的历史路线，本轮不实施合同审批或 Experience Compiler 集成。

2026-11-03 补充：后续采用以老板需求为中心的 Agent 能力层，暂不接入 Skills。优先在已交付事实/证据上建立模型提案、服务端授权和受控工具执行，再逐项接入后续 Slice 的数据来源与记忆。设计和验收见 [Agent 能力与执行边界](agent-capabilities.md)；此安排不表示后续能力已经实现。

## 0 — 项目初始化（当前）

- Go Core（AGPL-3.0-only）与 TypeScript Experience Compiler（Apache-2.0）独立仓库、基础 CI。
- Provider Manifest 与 Work Experience Contract 最小草案。
- 文件校验、健康检查、确定性体验 IR 编译及共享样例测试。

## 1 — 协议与受控执行

- 冻结 ID、租户、版本、Authority、错误、Capability、Binding、ActionRequest、Execution 与 Evidence Schema。
- 实现 Native Provider 示例与显式信任配置下的发现、校验、注册和健康状态。
- 定义 Policy 接口，默认拒绝；接入身份来源，阻止客户端自报角色授予权限。
- 执行幂等键按租户、主体和目标隔离；同键不同载荷冲突；持久化执行与审计。
- PostgreSQL + Outbox；取消、超时与未知结果不得触发盲目重试。

## 2 — 合同审批完整链路

- 虚构合同 Provider、领域 Pack、审批 WorkItem 与授权后的 ContextSnapshot。
- Compiler 生成决策体验；Renderer 处理证据展开、确认和动作回传。
- 服务端治理、必要审批、效果验证、Evidence、Event 与契约 revision 更新。
- 验收：拒绝越权、拒绝过期状态；重复请求不重复执行；失败可追踪；换 Provider 不修改 Core。

## 3 — 扩展接入与体验

- 基于需求逐个引入 OpenAPI / MCP / A2A / Event Binding 和 SDK。
- Experience 连续性、交互反馈、布局与自适应；模型辅助编译与确定性降级。
- Integration Studio、更多 Domain Pack、可观测性和部署工具。

当前未实现：生产鉴权、多租户隔离、数据库、真实 ERP 接入、LLM、渲染器、业务执行、自动生成完整应用。
