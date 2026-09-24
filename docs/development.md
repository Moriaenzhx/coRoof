# Development

需要 Go 1.26+。在本仓库根目录运行 go fmt ./...、go vet ./...、go test ./...、go build ./cmd/coroof。CI 在 Linux 上额外运行 race 检查。

Experience Compiler 位于 https://github.com/SolanZhang/experience-compiler ，使用 Node.js 24+，可单独运行 npm ci、npm test、npm run demo。

协议规范以 Experience Compiler 的 spec/ 为共享发布源，本仓库保留 Apache-2.0 快照，使独立检出无需联网构建。协议变更需同步两仓库的 spec/、examples/、Go 模型与生成的 TypeScript 类型。在 Compiler 运行 npm run generate，再运行 npm run test:integration -- "../coRoof core"（参数为本仓库路径）。该测试同时检查协议快照一致、Go 序列化和 TypeScript 编译结果。

Compiler CI 使用固定的 Core 提交进行集成测试；更改协议时需要更新该固定提交并协调两个仓库。不要手工编辑生成的 TypeScript 文件。

本地开发工具、缓存、依赖和构建产物不提交。服务仅提供健康检查与版本接口；数据 API 仍待实现。公开仓库只使用虚构样例。
