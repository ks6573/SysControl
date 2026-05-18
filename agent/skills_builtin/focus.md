---
name: focus
description: Enter a focused work block — DnD on, deep-work timer, distractions muted.
trigger: "focus time|deep work|leave me alone"
tools: [toggle_do_not_disturb, do_not_disturb_status, set_reminder, notify_user, set_volume, get_frontmost_app]
permissions: [allow_notes]
---

You are running the **focus** skill. The user wants to disappear into a work
block. Be efficient — minimal chatter, maximum action.

Default block length is 60 minutes unless the user specified one in their
message (e.g. "focus 90 minutes" → 90).

Steps:

1. `do_not_disturb_status` — record the prior state so you can restore it.
2. `toggle_do_not_disturb(enabled=true)`.
3. `set_volume(20)` — quiet by default.
4. `set_reminder(text='End focus block', when='in <block_length> minutes')`.
5. `notify_user(title='Focus mode active', body='<block_length> min · DnD on · I'll
   ping you when the block ends', sound=false)`.

Reply with a single line:

    Focus mode active · DnD on · <block_length>m · timer set.

Do not ask follow-up questions; if the user wants different settings they will
say so.
