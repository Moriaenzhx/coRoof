# coRoof

**AI 原生企业工作环境 · AI-native enterprise work environment**

coRoof 将企业现有系统、业务语义、能力、Agent、治理与体验生成组织在一起，让人围绕目标和工作行动。本仓库是 Go 实现的 Enterprise Work Runtime。

> pre-alpha 初始化骨架。协议为可演进的 v0.1 草案；尚未实现生产鉴权、持久化、真实企业执行或完整 UI。

## 架构

Human / Agent → [Experience Compiler](https://github.com/SolanZhang/experience-compiler) → Work Experience Contract / ActionRequest → **Go Runtime** → Provider → ERP / CRM / HR。

Core 描述工作、事实与能力，未来负责受控执行；Compiler 将授权过滤后的工作契约转为 Experience IR。系统差异位于 Provider 边界，Core 不包含厂商专用业务逻辑。身份、策略、效果验证与证据约束整个执行路径。

## 开始开发

需要 Go 1.26+，在本仓库根目录运行：

```sh
go test ./...
go run ./cmd/coroof validate-provider examples/provider.json
go run ./cmd/coroof serve
```

服务默认监听 127.0.0.1:8080，仅提供 GET /healthz 和 /version；可用 serve -addr 127.0.0.1:9090 修改地址。Provider 校验仅验证离线文件，不进行远程发现、注册或执行。roundtrip-work 命令仅用于契约序列化测试，不代替 Schema 校验。

## 目录

| 路径 | 职责 |
| --- | --- |
| cmd/coroof | CLI 与进程入口 |
| internal/server | 健康检查与版本 HTTP 接口 |
| pkg/contract | Go 工作契约类型 |
| pkg/provider | Provider Manifest 与离线校验 |
| spec | JSON Schema 草案（Apache-2.0） |
| examples | 虚构协议样例（Apache-2.0） |
| docs | 架构、模型、开发说明与路线图 |

Go module 为 github.com/SolanZhang/coRoof。体验编译器在独立仓库中构建；本仓库构建不需要 Node.js。

当前已实现工程结构、协议草案、离线校验、健康检查和基础测试。下一条完整业务链路是合同审批：发现 → 授权上下文 → 工作契约 → 体验 → 治理执行 → 效果验证 → 证据与事件 → 重新编译。

阅读 [架构](docs/architecture.md)、[核心模型](docs/core-model.md)、[协议](spec/README.md)、[开发说明](docs/development.md) 和 [路线图](docs/roadmap.md)。

## License

除明确列出的例外外，本仓库代码和文档采用 [GNU AGPL v3 only](LICENSE)（SPDX: AGPL-3.0-only）。spec/ 与 examples/ 中的协议资料和虚构样例采用各自目录内的 Apache-2.0 许可证，便于独立实现和集成。Experience Compiler 单独采用 Apache-2.0。
