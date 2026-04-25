"""Per-save LLM token-usage accumulation."""

from __future__ import annotations

from dataclasses import dataclass, field

from storygen.storage.save import GameSave


@dataclass
class UsageTotals:
    """Mutable, in-memory tally of token usage during a sequence of agent calls.

    Used by WizardFlow during the wizard run (before a GameSave exists) and
    later merged into the GameSave via ``apply_to_save``.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    calls_by_model: dict[str, int] = field(default_factory=dict[str, int])

    def record(
        self,
        *,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        requests: int = 1,
    ) -> None:
        """Record a single agent call's token usage."""
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0
        self.requests += requests
        self.calls_by_model[model] = self.calls_by_model.get(model, 0) + 1

    def apply_to_save(self, save: GameSave) -> None:
        """Merge accumulated totals into ``save``'s persistent counters."""
        save.text_total_input_tokens += self.input_tokens
        save.text_total_output_tokens += self.output_tokens
        save.text_total_requests += self.requests
        for model, n in self.calls_by_model.items():
            save.text_calls_by_model[model] = save.text_calls_by_model.get(model, 0) + n


def record_usage_on_save(
    save: GameSave,
    *,
    model: str,
    usage: object,
) -> None:
    """Increment token totals on ``save`` from a pydantic-ai RunUsage object.

    Accepts ``object`` to avoid a hard dependency on pydantic_ai.usage in
    type signatures (the adapters already use loose typing). Reads
    input_tokens / output_tokens / requests via getattr so it tolerates
    pydantic-ai version drift.
    """
    input_tokens = getattr(usage, "input_tokens", None) or 0
    output_tokens = getattr(usage, "output_tokens", None) or 0
    requests = getattr(usage, "requests", None) or 1
    save.text_total_input_tokens += int(input_tokens)
    save.text_total_output_tokens += int(output_tokens)
    save.text_total_requests += int(requests)
    save.text_calls_by_model[model] = save.text_calls_by_model.get(model, 0) + 1
