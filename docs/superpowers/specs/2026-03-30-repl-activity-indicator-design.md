# REPL Activity Indicator Design

## Goal

Add a lightweight activity indicator to the Bourbon REPL so users can see that the
agent loop is still active even before the first streamed text chunk arrives.

## Context

The current REPL streaming path uses Rich `Live` to render accumulated assistant
text, but the live area only changes when `on_chunk()` is invoked. If the model or
upstream provider is slow to deliver the first token, the UI can look stalled even
while the request is still running.

## Proposed Design

Add a dynamic streaming renderable inside [repl.py](/Users/whf/github_project/build-my-agent/src/bourbon/repl.py)
that renders:

- a one-line Bourbon-themed activity indicator at the top
- the accumulated streamed text below it

The activity indicator should animate independently of chunk arrival by relying on
Rich Live's periodic refresh. That means the live renderable itself must compute its
frame from `time.monotonic()` at render time instead of only rebuilding on chunk
events.

## UI Behavior

- Before the first chunk: show a status like `Bourbon is thinking...`
- After at least one chunk: switch to `Bourbon is replying...`
- Use a short repeating "pour/fill" frame sequence next to the `🥃` motif
- Keep the existing final markdown re-rendering after streaming completes
- Keep the animation transient so it disappears when the final response is printed

## Implementation Notes

- Introduce a small helper class in [repl.py](/Users/whf/github_project/build-my-agent/src/bourbon/repl.py)
  to hold streamed text and render the animated status line
- Keep the scope local to REPL; no config surface is needed for this first version
- Preserve existing debug logging and pending-confirmation handling

## Testing

- Add unit tests for the renderable to verify:
  - it shows a "thinking" status before chunks
  - it shows a "replying" status after chunks
  - the rendered frame changes over time
- Keep existing REPL streaming tests passing
