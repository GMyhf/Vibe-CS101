# Vibe-cs101 学生使用教程

给《计算概论B（cs101）》《数据结构与算法B（cs201）》同学的个人学习智能体：
离线全文检索老师的课件与题解、AI 助教答疑（注明出处）、错题本 + 间隔复习。

> **数据都在你自己电脑上**：错题本、对话记录不上传任何服务器；
> 只有 AI 对话会把你的问题发给你自己配置的大模型服务商（如 DeepSeek）。

## 一、5 分钟上手（离线检索，不需要任何 API key）

前提：Python 3.11 及以上（`python3 --version` 查看；Windows 用 `py --version`）。

```bash
# 1. 克隆仓库（无第三方依赖，克隆即用）
git clone https://github.com/GMyhf/Vibe-CS101.git
cd Vibe-CS101

# 2. 一键下载预构建索引（约 40MB，每周一自动更新，含全部课件+题解）
python3 -m vibe_cs101 quickstart

# 3. 开始检索（中英文都行）
python3 -m vibe_cs101 search "动态规划"
python3 -m vibe_cs101 search "接雨水" --course cs101
python3 -m vibe_cs101 show 288          # 按编号看完整章节
```

> Windows 同学：把命令里的 `python3` 换成 `py -3`（或 `python`）。
> 没装 git 也可以在 GitHub 页面 Download ZIP 解压后进入目录。

索引覆盖的资料：两学期课件（每周讲义、cheatsheet、往年考题）+ 六套题解
（力扣简单/中等、力扣挑战、cs101.openjudge.cn、Codeforces、晴问、cs201 数算）。

## 二、开启 AI 助教（需要一个大模型 API key）

任意 OpenAI 兼容服务都可以，推荐 [DeepSeek](https://platform.deepseek.com/)
（国内直连、按量计费，问一次大约几分钱）：

1. 在 platform.deepseek.com 注册并创建 API key（`sk-` 开头）
2. 在仓库目录里配置：

```bash
cp .env.example .env      # 打开 .env，把 key 填进 VIBE_CS101_API_KEY=
```

3. 开始对话：

```bash
python3 -m vibe_cs101 ask "什么是单调栈？结合课件举个例题"
python3 -m vibe_cs101 chat        # 多轮交互式对话，exit 退出
```

助教回答前会先检索老师的课件和题解，并注明出处（来源 + 章节标题）；
资料没覆盖的内容它会明确说明。

**建议的问法**：
- 「第 11 周讲的 dp 递推写法没听懂，用最简单的例子讲一遍」
- 「OpenJudge 26977 接雨水怎么做？先给思路再给代码」
- 「往年机考里考过哪些贪心题？」
- 「我做错了力扣 42，帮我记到错题本，标签是单调栈」
- 「今天有哪些错题要复习？考考我」

## 三、错题本 + 间隔复习

做错的题记下来，系统按 **1 → 3 → 7 → 14 → 30 天**安排复习，
全部通过标记「已掌握」。三种用法任选：

```bash
# 方式 1：对话里直接说（推荐，AI 会自动关联题解）
python3 -m vibe_cs101 chat
你> 我做错了 OpenJudge 02533，原因是递归边界写错了，帮我记一下

# 方式 2：命令行
python3 -m vibe_cs101 mistake add "OpenJudge 02533 斐波那契" --course cs101 --tags "递归" --reason "边界写错"
python3 -m vibe_cs101 mistake due            # 今日待复习
python3 -m vibe_cs101 mistake review 1 good  # 复习结果：good 记住了 / again 还不会
python3 -m vibe_cs101 mistake stats          # 薄弱知识点分析

# 方式 3：Web 界面（见下一节）
```

考前用 `mistake stats` 看薄弱知识点排行，优先复习未掌握多的标签。

## 四、Web 界面（可选）

```bash
python3 -m vibe_cs101 serve
# 浏览器打开 http://127.0.0.1:8101
```

四个页面：💬 对话、🔍 检索、📌 错题本、📈 学习进度。只监听本机，数据不出你的电脑。

## 五、在 Claude Code / MCP 客户端里用（可选，进阶）

如果你用 Claude Code 写作业，可以把课件检索接进去：

```bash
claude mcp add vibe-cs101 -- python3 -m vibe_cs101.mcp_server
```

之后在 Claude Code 里问课程问题，它能直接检索老师的课件和题解。

## 六、常见问题

**Q: quickstart 下载失败？**
网络原因可重试；或到 [data-latest release](https://github.com/GMyhf/Vibe-CS101/releases/tag/data-latest)
手动下载 `index.db` 放到 `data/` 目录。也可以 `python3 -m vibe_cs101 update && python3 -m vibe_cs101 index`
自行构建（此方式只含题解；课件部分需要把课件仓库克隆到本仓库的上一级目录）。

**Q: 提问时报 LLM API 错误？**
`python3 -m vibe_cs101 info` 查看配置状态。确认 `.env` 里 key 填对、账户有余额；
用其他服务商时同时设置 `VIBE_CS101_BASE_URL` 和 `VIBE_CS101_MODEL`。

**Q: 索引内容旧了？**
重新跑一次 `python3 -m vibe_cs101 quickstart` 即可（每周一自动重建）。

**Q: AI 的回答可信吗？**
它被要求以老师资料为根据并注明出处，但仍可能出错——**代码要自己跑过、
思路要自己想通**。把它当讲解员，不要当标准答案。

**Q: 老师如果提供了在线版（网址 + 访问 key）？**
直接浏览器打开网址，首次会弹登录框，粘贴发给你的 key 即可，无需本地安装。
在线版每人的错题本相互隔离。
