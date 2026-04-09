from bourbon.prompt.types import PromptContext, PromptSection


class PromptBuilder:
    """Assembles system prompt from ordered sections."""

    def __init__(
        self,
        sections: list[PromptSection],
        custom_prompt: str | None = None,
        append_prompt: str | None = None,
    ) -> None:
        self._sections = sorted(sections, key=lambda section: section.order)
        self._custom_prompt = custom_prompt
        self._append_prompt = append_prompt

    async def build(self, ctx: PromptContext) -> str:
        if self._custom_prompt is not None:
            base = self._custom_prompt
        else:
            base = await self._assemble_sections(ctx)

        if self._append_prompt is not None:
            base = base + "\n\n" + self._append_prompt

        return base

    async def _assemble_sections(self, ctx: PromptContext) -> str:
        parts: list[str] = []
        for section in self._sections:
            if section.is_static:
                text = section.content
            else:
                text = await section.content(ctx)
            if text:
                parts.append(text)
        return "\n\n".join(parts)
