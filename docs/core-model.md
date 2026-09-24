# Core Model v0.1

## 定义与实例

Definition Model 描述规则：DomainPack、ResourceType、RelationType、CapabilityDefinition、EventType、WorkTemplate、PolicyBinding。

Runtime Model 描述发生的工作：Actor、Resource、Relation、Goal、WorkItem、ContextSnapshot、ActionRequest、ExecutionRecord、DomainEvent、DecisionRecord、EvidenceRecord、AuthorizationDecision。

State 属于 Resource、WorkItem、Goal 或 Execution，不是独立实体。ContextSnapshot 是有时效与授权范围的工作投影，不拥有事实。AuthorizationDecision 是决策记录，不是永久授权。

## 重要区分

| 概念 | 含义 |
| --- | --- |
| Resource | 可引用、关联和操作的企业语义对象 |
| CapabilityDefinition | 企业能够做什么及其输入、输出、风险和效果 |
| CapabilityBinding | 通过哪个 Provider 与传输方式完成能力调用 |
| ActionRequest | 某主体针对某对象发起的一次业务请求 |
| ExecutionRecord | 该请求的执行过程、验证结果和证据引用 |
| WorkExperienceContract | 已过滤的事实、工作、风险、证据、可用动作 |
| ExperienceIR | 编译器对展示和交互结构的决定 |

Authority 分为两个维度：对象所有权（EXTERNAL_SOR / COROOF_OWNED / DERIVED / EPHEMERAL），以及 Provider 数据权威（AUTHORITATIVE / REPLICA / DERIVED / REFERENCE）。两者不混为同一枚举。字段级 provenance 和 freshness 后续必须进入事实投影。

## 初始化实现范围

本次 Go 类型与 JSON Schema 仅覆盖 Provider 描述及 WorkExperienceContract 的最小可测试子集，其余模型是路线约束，尚无 Runtime 实现。Schema 是跨语言数据边界的依据。TypeScript 类型由 Schema 生成；Go 类型通过共享样例的序列化及 Schema 测试检查一致性。

工作契约包含：版本、ID、租户、revision、actor、work、focus、facts、attention、evidence、actions。动作 availability 是展示时的快照，执行时必须重新授权；旧 revision 不可直接作为执行许可。
