# Vibe-cs101: 课程计算机基础学习智能体

[![CI](https://github.com/GMyhf/Vibe-CS101/actions/workflows/ci.yml/badge.svg)](https://github.com/GMyhf/Vibe-CS101/actions/workflows/ci.yml)
[![Update index](https://github.com/GMyhf/Vibe-CS101/actions/workflows/update-index.yml/badge.svg)](https://github.com/GMyhf/Vibe-CS101/actions/workflows/update-index.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

面向 **cs101（计算概论B）/ cs201（数据结构与算法B）** 的课程学习智能体：
智能搜集任课老师的课件与题解，
建立本地全文索引，并通过带工具调用的 LLM 智能体回答问题——回答以老师的资料为根据并注明出处。

## 资料来源

- **课程课件**（本地克隆仓库，位于工作区根目录）
  - `2025fall-cs101/` — 2025 秋季 cs101 每周讲义、作业、cheatsheet、往年考题
  - `2026spring-cs201/` — 2026 春季 cs201 每周讲义、考试、题目列表
- **题解**（自动从上游 GitHub 下载，ETag 缓存）
  - 力扣简单/中等、力扣挑战（GMyhf/2024fall-cs101）
  - cs201 数算题解、晴问算法笔记（GMyhf/2024spring-cs201）
  - cs101.openjudge.cn、Codeforces（GMyhf/2020fall-cs101）

## 快速开始

零第三方依赖（仅 Python 3.11+ 标准库，含测试）。

> 🎓 **同学们看这里** → [学生使用教程 TUTORIAL.md](TUTORIAL.md)：
> `git clone` + `python3 -m vibe_cs101 quickstart` 两条命令即可离线检索，无需 API key。

```bash
cd vibe-cs101

# 0.（推荐）一键初始化：下载每周预构建的索引，跳过下面 1-2 两步
python3 -m vibe_cs101 quickstart

# 1. 下载/更新上游题解（约 20MB，ETag 缓存，重复运行只拉取变更）
python3 -m vibe_cs101 update

# 2. 建立全文索引（SQLite FTS5，中英文均可检索）
python3 -m vibe_cs101 index

# 3. 离线检索（无需 API key）
python3 -m vibe_cs101 search "动态规划" --course cs101
python3 -m vibe_cs101 show 288          # 查看完整章节

# 4. 配置 LLM（任意 OpenAI 兼容端点：DeepSeek / OpenAI / Kimi / GLM / 本地）
cp .env.example .env                     # 填入 API key
# 或：export DEEPSEEK_API_KEY=sk-...     # 或 OPENAI_API_KEY

# 5. 提问 / 对话
python3 -m vibe_cs101 ask "什么是单调栈？给个例题"
python3 -m vibe_cs101 chat              # 交互式多轮对话
python3 -m vibe_cs101 info              # 查看配置与索引状态

# 6. Web UI（对话 / 检索 / 知识库 / 题解查询 / 错题本 / 学习进度）
python3 -m vibe_cs101 serve             # http://127.0.0.1:8101

# 远程访问需先启用鉴权；多用户会自动隔离错题本和对话会话
# teacher 可进入管理页维护成员、课程资源和行为日志
python3 -m vibe_cs101 user add alice    # 推荐：创建用户（key 加盐哈希落盘，仅显示一次）
python3 -m vibe_cs101 user list         # 用户管理：add / list / reset / rm，即时生效
# 或临时用环境变量：export VIBE_CS101_AUTH_KEYS='alice:alice-key,bob:bob-key'
python3 -m vibe_cs101 serve --host 0.0.0.0 --port 8101
# 可选：直接启用 HTTPS（也可放在 Caddy/Nginx 等反向代理后）
python3 -m vibe_cs101 serve --host 0.0.0.0 --tls-cert fullchain.pem --tls-key privkey.pem

# 7. 错题本（也可以直接在对话里说“我做错了某题”，智能体会帮你记）
python3 -m vibe_cs101 mistake add "OpenJudge 26977 接雨水" --course cs101 --tags "单调栈" --reason "边界写错"
python3 -m vibe_cs101 mistake due       # 今日待复习
python3 -m vibe_cs101 mistake review 1 good   # 记录复习结果（good/again）
python3 -m vibe_cs101 mistake stats     # 薄弱知识点分析
```

也可 `pip install -e .` 后直接使用 `vibe-cs101` 命令。

## 工作原理

```
上游 GitHub 题解 ──update──▶ data/original/<github-repo>/*.md ─┐
                                                  ├─index──▶ data/index.db (SQLite FTS5)
本地课件仓库 (../2025fall-cs101, ../2026spring-cs201) ─┘              │
                                                                      ▼
用户提问 ──▶ Agent（LLM 工具调用循环）──▶ search_materials / read_section / list_sources
                     │
                     ▼
          以老师资料为根据、注明出处的回答
```

- **抓取** `fetch.py`：带 ETag 的条件请求，按 GitHub 仓库目录保存原文，
  失败时保留本地副本
- **索引** `indexer.py`：按标题层级把长 Markdown 切分成章节；对 CJK 字符做逐字
  分词预处理，使 FTS5 unicode61 支持中文检索（无需外部分词库）
- **检索** `store.py`：BM25 排序（标题加权），snippet 高亮，course/source 过滤
- **智能体** `agent.py` + `tools.py` + `llm.py`：OpenAI 兼容 chat/completions
  工具调用循环，最多 12 轮；最后一轮撤下工具强制给出文字回答
- **错题本** `journal.py`：从做题记录里找出“你在哪里丢分”。间隔复习
  （1/3/7/14/30 天，全过 → 已掌握），按标签/课程
  统计薄弱知识点。智能体可在对话中直接记错题、带你复习。单人模式存于
  `data/journal.db`；Web UI 多用户模式按 `data/journal-<user>.db` 隔离。
- **Web UI** `server.py` + `web/`：后端 REST API + 单页前端，保持零依赖：
  标准库 ThreadingHTTPServer + 无构建的原生 JS 单页应用。
  页面包括对话、检索、知识库、原生题解查询、错题本、学习进度和管理页。默认只监听
  127.0.0.1；绑定非本机地址时必须启用鉴权（环境变量 key 或 `user add` 创建的
  用户），并建议通过 `--tls-cert/--tls-key` 或反向代理启用 HTTPS。
  管理页支持成员管理、课程资源配置、学生行为日志翻页和 CSV 导出。
- **会话持久化** `sessions.py`：每轮对话后把完整上下文存入 `data/sessions.db`，
  服务重启后可从会话列表恢复继续；前端支持切换/删除历史会话。
- **用户管理** `users.py`：`vibe-cs101 user add/list/reset/rm`，key 加盐 SHA-256
  哈希存 `data/users.db`（不明文落盘），增删即时生效，与环境变量鉴权并存。
- **限流** `ratelimit.py`：滑动窗口，按用户限 API/对话频率、按 IP 限鉴权失败
  次数（防暴力试 key），超限返回 429 + Retry-After。

## 配置

| 环境变量 | 说明 |
|---|---|
| `VIBE_CS101_BASE_URL` | OpenAI 兼容端点，默认 `https://api.deepseek.com/v1` |
| `VIBE_CS101_API_KEY` | API key（也可用 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`） |
| `VIBE_CS101_MODEL` | 模型名，默认 `deepseek-chat` |
| `VIBE_CS101_DATA_DIR` | 数据目录，默认 `vibe-cs101/data/` |
| `VIBE_CS101_AUTH_KEY` | Web UI 单用户访问密钥；设置后用户名为 `owner` |
| `VIBE_CS101_AUTH_KEYS` | Web UI 多用户访问密钥，格式 `alice:k1,bob:k2` |
| `VIBE_CS101_RATE_API` | 每用户普通 API 限流，格式 `N/秒数`，默认 `120/60`，`0` 不限 |
| `VIBE_CS101_RATE_CHAT` | 每用户对话（LLM 调用）限流，默认 `10/60` |
| `VIBE_CS101_RATE_AUTHFAIL` | 每 IP 鉴权失败限流（防暴力试 key），默认 `10/300` |
| `VIBE_CS101_MAX_SECTION_CHARS` | read_section 单次返回字数上限，默认 `6000` |
| `VIBE_CS101_MAX_READ_SECTIONS` | 每轮对话最多读取的章节数，默认 `3` |

远程部署时，`python3 -m vibe_cs101 serve --host 0.0.0.0` 会在未配置 Web UI
鉴权时拒绝启动，避免把本地学习数据和 LLM 接口裸露到网络。浏览器登录后会把
key 保存在本机 `localStorage`，后续 API 请求使用 `Authorization: Bearer <key>`。

## MCP Server

MCP Server 让 Claude Code 等 MCP 客户端直接调用本项目的课程资料检索工具。先保证
`data/index.db` 已存在：

```bash
python3 -m vibe_cs101 quickstart
# 或：python3 -m vibe_cs101 update && python3 -m vibe_cs101 index
```

### Codex CLI

Codex 使用自己的 MCP 管理命令。推荐显式设置 `PYTHONPATH`，这样不依赖系统是否安装了 `pip`：

```bash
codex mcp add vibe-cs101 \
  --env PYTHONPATH=/home/rocky/git/Vibe-CS101 \
  -- python3 -m vibe_cs101.mcp_server
```

确认配置：

```bash
codex mcp list
codex mcp get vibe-cs101
```

如果已经添加过未带 `PYTHONPATH` 的配置，先删后加：

```bash
codex mcp remove vibe-cs101
codex mcp add vibe-cs101 \
  --env PYTHONPATH=/home/rocky/git/Vibe-CS101 \
  -- python3 -m vibe_cs101.mcp_server
```

如果你的 Python 环境有 `pip`，也可以选择安装包后再添加：

```bash
cd /home/rocky/git/Vibe-CS101
python3 -m pip install -e .
codex mcp add vibe-cs101 -- python3 -m vibe_cs101.mcp_server
```

添加后重启 Codex 或开启新的 Codex 会话，再这样提问：

```text
请用 vibe-cs101 检索 cs101 资料，解释单调栈，并列出引用来源。
```

### Claude Code

Claude Code 使用 `claude mcp add`。在仓库目录外也可添加，但推荐使用绝对路径，避免客户端从别的目录启动时找不到模块：

```bash
claude mcp add vibe-cs101 -- python3 -m vibe_cs101.mcp_server
# 或：
claude mcp add vibe-cs101 -- /usr/bin/python3 -m vibe_cs101.mcp_server
```

如果你没有把仓库安装到 Python 环境，先在仓库根目录执行一次：

```bash
python3 -m pip install -e .
claude mcp add vibe-cs101 -- python3 -m vibe_cs101.mcp_server
```

添加后重启 Claude Code，问问题时明确要求它使用课程资料，例如：

```text
请用 vibe-cs101 检索 cs101 资料，解释“单调栈”，并列出引用来源。
请先 list_sources，再 search_materials 查询“接雨水”，必要时 read_section 读取全文。
```

可用工具：

- `list_sources`：列出当前索引中的课程和来源名。
- `search_materials`：按关键词检索课件/题解，可传 `course`、`source`、`limit`。
- `read_section`：按 `search_materials` 返回的 `section_id` 读取完整章节。

## 测试

```bash
python3 -m unittest discover -s tests        # 纯标准库，无需安装任何依赖
```

## Roadmap

- [x] MCP server，把 search/read 工具暴露给 Claude Code 等客户端
- [x] 定时自动 update + index（GitHub Actions 每周一重建，索引发布在
      [data-latest release](https://github.com/GMyhf/Vibe-CS101/releases/tag/data-latest)，
      下载 `index.db` 放到 `data/` 即可跳过 update/index 步骤）
- [x] Web UI（后端 API + 单页前端架构，零依赖实现：`serve` 命令）
- [x] 错题本 / 学习进度跟踪（`mistake` 命令 + 智能体工具 + Web 页面）
- [x] 多用户 / 远程部署基础能力（Bearer 鉴权、按用户隔离错题本和会话、可选 TLS）
