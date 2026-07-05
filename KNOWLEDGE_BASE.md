# Knowledge Base Maintenance

This project has two knowledge-base layers:

- Browsable source files shown in the left-panel "知识库".
- The search/chat index stored at `data/index.db`.

After adding or updating source files, rebuild the index so search and chat can use the new content.

## Update Existing Courseware

Courseware repositories live beside this repo under `/home/rocky/git/`, for example:

```bash
cd /home/rocky/git/2025fall-cs101 && git pull
cd /home/rocky/git/2026spring-cs201 && git pull
```

Then rebuild Vibe-CS101 data:

```bash
cd /home/rocky/git/Vibe-CS101
python3 -m vibe_cs101 update
python3 -m vibe_cs101 index
```

`update` downloads upstream solution Markdown files. `index` rebuilds the SQLite FTS index.

## Add A New Courseware Repository

Clone the repository under `/home/rocky/git/`:

```bash
cd /home/rocky/git
git clone https://github.com/OWNER/REPO.git
```

Register it in `vibe_cs101/config.py` under `LOCAL_SOURCES`:

```python
LocalSource(
    name="2026fall-cs101",
    path=WORKSPACE_DIR / "2026fall-cs101",
    title="2026 秋季 cs101 课件",
    course="cs101",
)
```

Then rebuild the index:

```bash
cd /home/rocky/git/Vibe-CS101
python3 -m vibe_cs101 index
```

Restart the service after changing `config.py`.

## Update The Solution Browser

The native "题解查询" panel uses locally generated `sol101` Markdown files. To refresh them manually:

```bash
cd /home/rocky/git/Vibe-CS101
scripts/update_sol101.sh
```

A system cron job already runs this daily at 04:20:

```text
/etc/cron.d/vibe-cs101-sol101
```

## Restart Rules

- Updating existing files and rebuilding `data/index.db`: restart is usually not required.
- Changing `vibe_cs101/config.py`, adding a source, or changing code: restart the service.
- "管理 → 课程资源配置" controls which resources are enabled per course; it does not download files.
