import asyncio
from pathlib import Path

from bourbon.prompt.types import PromptContext, PromptSection


CTX = PromptContext(workdir=Path("/tmp/test"))


def run(coro):
    return asyncio.run(coro)


def test_static_sections_assembled_in_order():
    from bourbon.prompt.builder import PromptBuilder

    sections = [
        PromptSection(name="b", order=20, content="second"),
        PromptSection(name="a", order=10, content="first"),
    ]
    builder = PromptBuilder(sections=sections)
    result = run(builder.build(CTX))
    assert result.index("first") < result.index("second")


def test_dynamic_section_called_with_context():
    from bourbon.prompt.builder import PromptBuilder

    calls = []

    async def factory(ctx: PromptContext) -> str:
        calls.append(ctx)
        return "dynamic content"

    sections = [PromptSection(name="dyn", order=10, content=factory)]
    builder = PromptBuilder(sections=sections)
    result = run(builder.build(CTX))
    assert result == "dynamic content"
    assert calls[0] is CTX


def test_custom_prompt_replaces_all_sections():
    from bourbon.prompt.builder import PromptBuilder

    sections = [PromptSection(name="a", order=10, content="should not appear")]
    builder = PromptBuilder(sections=sections, custom_prompt="custom")
    result = run(builder.build(CTX))
    assert result == "custom"
    assert "should not appear" not in result


def test_empty_string_custom_prompt_is_valid():
    from bourbon.prompt.builder import PromptBuilder

    sections = [PromptSection(name="a", order=10, content="should not appear")]
    builder = PromptBuilder(sections=sections, custom_prompt="")
    result = run(builder.build(CTX))
    assert result == ""


def test_append_prompt_appended_after_base():
    from bourbon.prompt.builder import PromptBuilder

    sections = [PromptSection(name="a", order=10, content="base")]
    builder = PromptBuilder(sections=sections, append_prompt="extra")
    result = run(builder.build(CTX))
    assert result == "base\n\nextra"


def test_append_prompt_appended_after_custom_prompt():
    from bourbon.prompt.builder import PromptBuilder

    builder = PromptBuilder(sections=[], custom_prompt="custom", append_prompt="extra")
    result = run(builder.build(CTX))
    assert result == "custom\n\nextra"


def test_empty_section_content_excluded():
    from bourbon.prompt.builder import PromptBuilder

    async def empty_factory(ctx: PromptContext) -> str:
        return ""

    sections = [
        PromptSection(name="a", order=10, content="present"),
        PromptSection(name="b", order=20, content=empty_factory),
    ]
    builder = PromptBuilder(sections=sections)
    result = run(builder.build(CTX))
    assert result == "present"
