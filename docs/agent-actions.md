# 阶段 3：Agent 提案与本人确认

2026-11-04。沿用阶段 2 的权限、模型额度、步骤幂等和会话边界，不引入第二个草稿或决策系统。

- 工作详情选择「AI 整理」，提交进展原文。任务仅允许生成 summary / lifecycle_status / needs_support 三个字段；模型输出的 approved、角色、凭据或工具字段不被接受。LangChain 仍负责供应商适配。
- 服务端核对当前工作版本、权限与未结束状态，保存现有 UpdateDraft；此时没有业务事件或投影变化。LangGraph `interrupt()` 持久化等待作者。
- 原作者查看原文和提案，可编辑草稿。每次编辑检查 revision，新的 revision 对应新的等待点。原作者单独点击确认后，HTTP 入口验证当前身份与原任务会话，再通过 `Command(resume=...)` 进入原有确认事务。
- Agent 完成的、可验证引用的回答可以准备 Decision。准备者必须是当前企业 Owner，分析属于本人且未过期；准备与确认都会核对事实/信号版本。其他 Owner 可以看企业决策，但不能代替准备者确认。确认后继续使用现有实际结果记录与依据引用。

当前页面先展示结论和建议下一步，证据、处理过程和其他方案折叠。老板点击“处理这件事”仅准备方案，在居中详情中核对首个建议安排及预填的跟进文字；可展开“修改这个安排”调整方案、后续安排和可选时间。最后明确点击“确认这个安排”才进入原确认命令；预选、预填、打开详情或读取历史均不等于确认。确认只记录安排，不自动通知同事、分配事项或改变工作状态。分析超过三十分钟或证据已变化时，当前入口先要求重新核对；他人方案保持等待准备者确认，保存失败保留编辑内容。

全局工作、证据、资料和业务确认详情统一居中按需打开；查询处理浮层仍为独立非模态入口，可收起和跨页保留。企业概览优先显示“需要你处理”和“项目进展”，再呈现紧凑动态全景；老板从“我的工作 → 等我确认与跟进”处理本人安排，从个人设置查看以前的处理经验。布局简化不减少来源可查性、作者确认、版本或幂等校验。

检查点仅保存目标 ID、版本、确认请求哈希和提交标记，不能授予权限。等待前没有非幂等业务效果；确认节点调用已有事务服务，在同一事务中追加 WorkEvent 与更新投影/审计。图保存失败或进程在业务提交后中断时，明确重试只返回同一命令的原结果，不再次改变工作。PostgreSQL advisory lock 避免多进程并发推进同一确认图，断连接自动释放；SQLite 仅用于辅助测试。

只读任务保持每次推进最多一次模型调用。草稿任务只做一次结构化提案；刷新或页面重新打开不会自动调用模型，也不会自动确认。直接父查询仅用于有边界的只读追问，不用于草稿或后台任务，也不赋予业务确认权限，限制见 [读取循环](agent-read-loop.md#有边界的追问与知识目录)。Coding Plan 的本轮单连接本机例外仅用于明确授权的连接测试与前台 Agent 交互，不扩展为业务写入授权或后台任务；正式应用仍使用经过验证且适用的通用 MaaS 配置。未配置时显示配置缺口，规则草稿单独标明非 AI。

数据库迁移为 `0007_agent_drafts`，仅追加 AgentRun.task 与草稿引用。PostgreSQL 原位 ALTER；SQLite 迁移按 Alembic 的表复制流程保留检查约束与子表记录，并做 foreign_key_check。生产并发验收只以 PostgreSQL 为准。

官方机制参考：[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。coRoof 复用这些机制；租户授权、事实版本和确认事务属于应用业务规则。

验收入口：`backend/tests/test_agent_actions.py`、Web 工作/问答交互测试，以及 `scripts/agent_acceptance.py --actions --config-file <ignored-test-config> --database-url <dedicated-test-db> --report <ignored-report>`。真实开发报告 `.local/agent-actions-acceptance.json` 不进入 Git；调用方不能通过 HTTP 启用测试配置。
