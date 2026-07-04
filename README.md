# Vibe-cs101: 个人计算机基础学习智能体

类似 [Vibe-Trading](https://github.com/GMyhf/Vibe-Trading) 的个人学习智能体：
智能搜集任课老师的 **cs101（计算概论B）/ cs201（数据结构与算法B）** 课件与题解，
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

```bash
cd vibe-cs101

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
```

也可 `pip install -e .` 后直接使用 `vibe-cs101` 命令。

## 工作原理

```
上游 GitHub 题解 ──update──▶ data/original/*.md ─┐
                                                  ├─index──▶ data/index.db (SQLite FTS5)
本地课件仓库 (../2025fall-cs101, ../2026spring-cs201) ─┘              │
                                                                      ▼
用户提问 ──▶ Agent（LLM 工具调用循环）──▶ search_materials / read_section / list_sources
                     │
                     ▼
          以老师资料为根据、注明出处的回答
```

- **抓取** `fetch.py`：带 ETag 的条件请求，失败时保留本地副本
- **索引** `indexer.py`：按标题层级把长 Markdown 切分成章节；对 CJK 字符做逐字
  分词预处理，使 FTS5 unicode61 支持中文检索（无需外部分词库）
- **检索** `store.py`：BM25 排序（标题加权），snippet 高亮，course/source 过滤
- **智能体** `agent.py` + `tools.py` + `llm.py`：OpenAI 兼容 chat/completions
  工具调用循环，最多 12 轮；最后一轮撤下工具强制给出文字回答

## 配置

| 环境变量 | 说明 |
|---|---|
| `VIBE_CS101_BASE_URL` | OpenAI 兼容端点，默认 `https://api.deepseek.com/v1` |
| `VIBE_CS101_API_KEY` | API key（也可用 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`） |
| `VIBE_CS101_MODEL` | 模型名，默认 `deepseek-chat` |
| `VIBE_CS101_DATA_DIR` | 数据目录，默认 `vibe-cs101/data/` |

## MCP Server

把检索工具暴露给 Claude Code 等 MCP 客户端（stdio 传输）：

```bash
claude mcp add vibe-cs101 -- python3 -m vibe_cs101.mcp_server
```

提供 `search_materials` / `read_section` / `list_sources` 三个工具。

## 测试

```bash
python3 -m unittest discover -s tests        # 纯标准库，无需安装任何依赖
```

## Roadmap

- [x] MCP server，把 search/read 工具暴露给 Claude Code 等客户端
- [ ] Web UI（参照 Vibe-Trading 的 FastAPI + React 架构）
- [ ] 错题本 / 学习进度跟踪（参照 Vibe-Trading 的 Shadow Account 思路）
- [ ] 定时自动 update + index（GitHub Actions 或本地 cron）
