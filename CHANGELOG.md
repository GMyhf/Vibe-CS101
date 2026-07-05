# Changelog

## 2026-07-05

### Added
- Added role-based Web UI users: `teacher`, `assistant`, and `student`.
- Added teacher permissions for adding users, changing user roles, managing course resources, and viewing student behavior logs.
- Added assistant permissions for managing course resources and viewing student behavior logs.
- Added student restrictions so students can use chat, search, library, mistakes, and progress features without access to admin APIs.
- Added behavior audit logging for chat, search, section reads, library views/downloads, mistake actions, progress views, and admin operations.
- Added course resource configuration so teachers and assistants can specify enabled courseware and solution sources per course.
- Added a Web UI management page for user management, course resources, and student behavior logs.
- Added CLI support for `user add --role teacher|assistant|student`.
- Added structured upstream solution storage under `data/original/<github-repo>/`.
- Added member profile fields: student ID, display name, department, and join time.
- Added batch student import from pasted rows using newline, comma, semicolon, space, or tab separators.
- Added member CSV export with student ID, name, department, role, join time, last seen, and username.
- Added member key reset and member deletion actions for teachers.
- Added pagination controls and CSV export for student behavior logs in the management page.
- Added a left-panel `sol101` solution-search tool served locally from `/sol101/`, built from `https://github.com/FuYnAloft/sol101`.
- Added `scripts/update_sol101.sh` and `scripts/update_sol101.py` to build the local `sol101` solution site from all answer sources supported by FuYnAloft/sol101.
- Added a system cron job at `/etc/cron.d/vibe-cs101-sol101` to refresh and rebuild the local `sol101` site daily at 04:20.

### Changed
- Migrated existing persistent users to the default `teacher` role to preserve administrator access after upgrade.
- Restarted the remote service on `http://10.129.81.235:8101` after loading the configured `.env`.
- Redesigned management screens to match the course-admin style: knowledge-base cards, member stats, large bordered tables, and a batch-import dialog.
- Renamed the ambiguous member role action from `保存` to automatic role saving when the role selector changes.
- Restored true streaming for final chat answers, including turns where the model decides no more tools are needed.
- Flushed SSE events immediately so browser clients can render chunks as they arrive.
- Clarified HTTP 524 LLM errors as upstream gateway timeouts and suggested retrying, shortening context, or changing the model endpoint.
- Added broad-query fallback for material search so multi-keyword questions do not return empty results when no single section matches every term.
- Restored the prebuilt course/solution index in `data/index.db` for live search-backed answers.
- Added mistake item links and detail view: records can now store an original problem URL, open a single mistake detail, and jump to the linked solution section when available.
- Added automatic OpenJudge problem-link inference and normalized Chinese/English tag separators in mistake records.
- Redesigned search results into compact cards with course/source badges, cleaner metadata, highlighted snippets, and explicit open actions.
- Changed search result opening to show the whole indexed Markdown document by default, with rendered Markdown and an optional matched-section view.
- Improved search reading flow: full-document view now scrolls to and highlights the matched section, search cards show 10 results by default with "show more", and snippet highlights are based on the current query terms.
- Fixed member-management role filters: student/assistant/teacher tabs now filter the table, and the static pagination footer was replaced with an accurate visible/total count.
- Clarified course resource configuration in the admin UI: it controls which courseware/solution sources are available to course-scoped search and chat, without deleting original files.
- Applied enabled course resources to `/api/search` and the agent `search_materials` tool when a course is specified.
- Added knowledge-base display paths so local courseware files appear under their GitHub repository name, while view/download actions still use the real relative file path.
- Cloned the missing `2026spring-cs201` courseware repository so the left-panel knowledge base shows the 2026 spring cs201 materials.
- Downloaded upstream solution Markdown files into `data/original/<github-repo>/` via `python3 -m vibe_cs101 update`.
- Changed the left-panel `sol101` tool from an external GitHub Pages iframe to a local Vibe-CS101-served static site.
- Added timeout protection to the `sol101` update script so cron jobs do not hang indefinitely on slow GitHub or source-update requests.
- Expanded the local `sol101` build from only OpenJudge/Codeforces to every upstream-supported answer set, including LeetCode, Sunnywhy, and C++.
- Reworked the left-panel solution search from an embedded VitePress iframe into a native Vibe-CS101 interface with solution-set filters, local search, and Markdown reading.
- Extended `/api/admin/logs` with `total`, `limit`, and `offset` metadata, and added `/api/admin/logs/export` for filtered CSV downloads.
- Fixed CSV download responses by removing a local `quote` import collision that could truncate export responses.
- Added `/api/solutions/list?set=...` so the native solution browser can show the complete problem list for each solution set.
- Changed the native solution browser to open a solution-set directory by default, list every problem number and title, and render Markdown with code-block copy controls.
- Matched the solution-set list order to the upstream `sol101` sidebar order, simplified problem cards to problem number and title, removed the duplicated reader title, and added Previous/Next page navigation below each solution.
- Switched the live LLM model setting from unsupported `gpt-5.2` to `gpt-5.4` for the configured `surplustoken.com` endpoint.
- Simplified the member-management name column so it shows only the display name, not the username/student ID twice.
- Updated the student tutorial and README with online deployment usage, per-user keys, role-based management, behavior-log disclosure, knowledge-base browsing, and the native solution browser workflow.
- Removed external project references from README and expanded the MCP Server section with setup and usage examples for Claude Code.
- Added Codex CLI-specific MCP setup instructions, including `codex mcp add`, verification commands, and a `PYTHONPATH` alternative.

### Verified
- Confirmed `.env` is active through `/api/info`: `llm_configured` is `true`, model is `gpt-5.2`.
- Confirmed the existing `remote` user has the `teacher` role and admin permissions.
- Confirmed the service is listening on `10.129.81.235:8101`.
- Built the local `sol101` VitePress static site into `data/sol101/docs/.vitepress/dist`; the served homepage now includes OpenJudge, Codeforces, LeetCode, Sunnywhy, and C++ entries.
- Rebuilt `data/index.db`; `/api/info` reports 5,521 indexed sections including 221 `cpp` solution sections.
- Confirmed the system cron daemon is active and `/etc/cron.d/vibe-cs101-sol101` is installed.
- Ran the full test suite: `python3 -m unittest discover -s tests` passed with 125 tests.
- Verified the live behavior-log pagination endpoint and CSV export on `http://10.129.81.235:8101`.
- Verified the live `oj` solution list returns all 377 OpenJudge problems and includes `24834: 通配符匹配`.
- Verified local OpenJudge navigation order around `E01218: THE DRUNK JAILER`.
- Verified a live chat request returns normally with `gpt-5.4`.
- Updated and verified the live `remote` teacher profile as student ID `0006173231`, display name `闫宏飞`.

### Notes
- Behavior logs include user actions and chat question summaries. Teachers and assistants can view these logs, so student-facing usage notes should disclose this.
- Each member has an individual access key. Plaintext keys are shown only when a member is created, batch-imported, or reset; exported member CSV files do not include keys.
