---
name: handoff
description: Summarise the current session into a markdown handoff for a teammate.
tools: [read_memory]
---

You are running the **handoff** skill. The user wants a clean, copy-pasteable
handoff document for whoever picks up this work next.

Compose a markdown document with exactly these sections:

# Context

A 2-3 sentence framing: what we were working on, why it matters, where we are.

# What's Done

Bulleted list of changes shipped or decisions made in this session. Reference
file paths and concrete artifacts.

# What's Open

Bulleted list of TODOs, blockers, and known unknowns. Be specific — "Investigate
slowdown in `core.py:_render_tool_summary`" beats "Performance work".

# Next Step

One sentence: the single best next move.

# Reference

Any notes from `read_memory` that are relevant, plus any links/file paths
worth carrying forward.

Stay terse — this is a handoff, not a memoir. The reader is also smart and
busy.
