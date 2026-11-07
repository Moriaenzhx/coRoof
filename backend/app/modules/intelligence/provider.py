"""Provider consumes authorized input; it has no database, tools or external credentials."""

from typing import Protocol

from app.core.schemas import ProposedFields


class UpdateProvider(Protocol):
    name: str
    model: str
    prompt_version: str

    def propose(self, raw_text: str) -> ProposedFields: ...


class RulesProvider:
    name = "rules"
    model = "deterministic-no-llm"
    prompt_version = "rules-v1"

    def propose(self, raw_text: str) -> ProposedFields:
        # Deliberately conservative: retain the original text; do not guess dates or completion.
        needs_support = (
            True
            if any(word in raw_text for word in ("需要", "阻塞", "晚到", "延期", "卡住"))
            else None
        )
        return ProposedFields(summary=raw_text, needs_support=needs_support)


def get_provider() -> UpdateProvider:
    return RulesProvider()
