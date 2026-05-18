---
name: cleanup
description: Find space-reclaim candidates in ~/Downloads and ~/Library/Caches.
trigger: "free up space|clean up disk|low disk space"
tools: [get_disk_usage, find_large_files, cleanup_downloads, cleanup_caches, summarize_directory]
permissions: [allow_file_read]
confirm: true
---

You are running the **cleanup** skill. NEVER delete anything in this run — your
job is to assemble a candidate list and stop. Deletion happens only after the
user explicitly confirms.

Steps:

1. `get_disk_usage` — capture current free space.
2. In parallel:
   - `cleanup_downloads(older_than_days=30, dry_run=True)`
   - `cleanup_caches(target='user', dry_run=True)`
   - `find_large_files(min_size_mb=200, paths=['~/Downloads', '~/Desktop', '~/Movies'])`
3. Sort everything by size, descending.

Produce a single report:

- **Reclaimable now** — total MB.
- **Top Candidates** — table (path, size, last modified).
- **Caches** — top 5 cache subdirectories with sizes.
- **Suggested Next Step** — a single command the user can paste (e.g.
  `cleanup_downloads(older_than_days=30, dry_run=false)`).

Do NOT call any tool with `dry_run=false` in this skill.
