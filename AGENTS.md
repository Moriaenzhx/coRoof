# coRoof development

- Read `README.md`, `docs/architecture.md`, `docs/domain-model.md` and the requested Slice before changing behavior. Do not implement a later Slice without the user's request.
- Inspect `git status` first. Preserve existing work; do not reset or replace unrelated files.
- V1 business code lives in `apps/web` and `backend`. The existing Go Runtime and `spec/` remain independent; changing the shared protocol requires its original cross-repository workflow.
- All organization-owned facts require tenant-scoped server authorization and composite tenant foreign keys. Client-provided roles are never authority.
- Business changes append WorkEvent and update projections in one transaction. Drafts require explicit author confirmation. Preserve idempotency and version checks.
- Database changes use Alembic. Never use startup `create_all` or destructive resets on an existing database.
- OpenAPI is the DTO source. Regenerate `packages/api-client` instead of maintaining a second set of TypeScript models.
- Keep mock identity and rules fallback visibly labeled. Production remains blocked until real identity/delivery and deployment controls exist.
- Follow the reference's quiet, light organization panorama and detail drawers. Missing data is unknown, never invented health.
- Run Python Ruff/format/mypy/pytest, Web format/types/interactions/build, and existing Go checks. PostgreSQL is required for concurrency acceptance. See `docs/v1-development.md`.
- Never commit credentials, local databases, dependency directories, generated build output or synthetic data presented as real customer data.
