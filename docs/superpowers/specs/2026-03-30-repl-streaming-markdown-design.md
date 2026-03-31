# REPL Streaming Markdown Design

## Goal

Restore true streaming output in the Bourbon REPL while keeping markdown rendering
visually correct during the stream.

## Problem

The previous mitigation removed raw streamed body output from the live area and left
only an activity indicator. That fixed mixed raw/rendered output, but it also
removed real streaming text.

The underlying issue is that token-by-token markdown is often incomplete. Rendering
the whole raw buffer directly causes visible artifacts, while rendering only at the
end removes streaming entirely.

## Design

Use an incremental render strategy in the REPL live display:

- keep a full accumulated text buffer
- split it into a stable markdown prefix and a pending tail
- render the stable prefix as markdown during the stream
- render the pending tail as plain text below it

The split should be conservative. The stable prefix only includes content that is
unlikely to be reinterpreted by later tokens. The pending tail buffers incomplete
structures such as:

- an unfinished final line
- an unclosed fenced code block
- a trailing line with unbalanced inline markers like `**`

## Expected Behavior

- users continue to see streamed text during generation
- already-complete markdown sections render progressively
- incomplete trailing fragments stay buffered until they are safe to render
- the final response still gets a full final render at the end
