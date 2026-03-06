# EfficientResearch

给定一个研究 topic，自主完成 **探索 → 校对 → 实验设计 → 写作** 的完整科研流程，输出研讨会级别的 LaTeX 论文。

---

## 系统架构

```
Phase 1 · Explore    Ideator → Scout → DeepResearcher
Phase 2 · Review     Skeptic ⟲ DeepResearcher        (回环：最多 2 次)
Phase 3 · Experiment Experimenter
Phase 4 · Write      Writer ⟲ [DeepResearcher | Experimenter | self]  (回环：最多 3 次)
Phase 5 · Edit       Editor → LaTeX
```

**7 个 Agent，各司其职：**

| Agent | 职责 | 输出 |
|---|---|---|
| **Ideator** | 生成 3–10 个可证伪假设 | `HypothesisCard[]` |
| **Scout** | ArXiv 文献粗筛，选择最优 1–2 个假设 | `related_work`, `selected_ids` |
| **DeepResearcher** | 深度文献检索（ArXiv + Semantic Scholar），构建注释书目 | `annotated_bib`, `baseline_checklist`, `gap_summary` |
| **Skeptic** | 模拟对抗评审员，列出拒稿风险与必做实验 | `rejection_risks`, `required_experiments` |
| **Experimenter** | 设计详细实验方案并进行多方理论验证（不直接跑实验） | `experiment_plan`, `theoretical_validation`, `result_tables`（可选占位） |
| **Writer** | 基于上述全部产出写 LaTeX 论文（9 章节） | `sections` dict |
| **Editor** | 润色学术语气，保留所有标注标签 | 改进后的 `sections` |

**迭代回环：**
- Skeptic 发现 ≥3 条证据缺口 → DeepResearcher 用 `rejection_risks` 作为精准搜索词重新检索
- Writer 质量门失败（引用/基线不足）→ 回到 DeepResearcher + Skeptic
- Writer 质量门失败（实验覆盖不足）→ 回到 Experimenter
- Writer 质量门失败（过度推测）→ Writer 带 `fix_list` 自我修正

**写作规范**：Writer/Editor 的写作风格参考 [awesome-ai-research-writing](https://github.com/Leey21/awesome-ai-research-writing) 模板库（丰满、合理、长度合适，避免 AI 腔）。

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 LLM

**使用 OpenAI API（推荐）：**
```bash
export OPENAI_API_KEY="sk-..."
export EFFICIENT_RESEARCH_MODEL="gpt-4o"   # 默认 gpt-4o-mini
```

**使用本地 vLLM：**
```bash
./env_prepare.sh          # 下载 Qwen3.5-9B + 启动 vLLM（需要 GPU）
```

### 3. 编写 input.md

**仅需给定 input.md 即可开启任务。** 任务可能长时间执行（数小时至数十小时），建议使用 `nohup ./run.sh input.md --browser > run.log 2>&1 &` 或 tmux。

```markdown
Topic: 你的研究主题（中英文均可）

## Problem
- 背景和现状描述
- 核心问题

Venue: Workshop, 4-6 pages, double-column

# 可选字段（均可在 input.md 中填写，或通过 run.sh 参数传入）
Scope: full
Sections: experiments, results, conclusion   # 仅重写这些章节时填写（需先跑过全流程）
Thinking: 1                                  # 浏览器模式下开启 thinking（建议配合 o1 等推理模型）
Focus: system                                # 研究偏好：system（系统/架构/算法）| theory | empirical | analysis，Ideator/Scout 会偏向该方向
```

### 4. 运行

```bash
./run.sh                    # 读取 input.md，使用 OpenAI API
./run.sh --local            # 使用本地 vLLM
./run.sh --input my.md      # 指定其他输入文件

# 浏览器模式（免 API Key，不占用日常 Chrome）
./run.sh --browser          # 会自动弹出**独立** Chrome 窗口，首次请在窗口中登录 ChatGPT，之后保持登录
# 若一直提示「验证是否为机器人」：见 docs/BROWSER_LLM_OPTIMIZATION.md；可尝试 rm -rf ~/.chatgpt-bot-profile 后重新运行并手动完成一次验证

# 自动登录（Cookie 导入）：在已登录的浏览器里导出 cookie，打开即已登录，无需每次手动登
export EFFICIENT_RESEARCH_COOKIE_FILE="$HOME/cookies_chatgpt.json"
./run.sh --browser
# 导出方式：Chrome 安装扩展如 Cookie-Editor，打开 chatgpt.com 并登录后导出为 JSON，保存为上述文件即可

# 开启 thinking 模式（建议在 ChatGPT 网页中选择 o1 等推理模型）
./run.sh --browser --thinking
# 或在 input.md 中写 Thinking: 1

# 仅重写部分章节（前提：artifacts/runs 中已有 01_ideator … 05_experimenter 与 06_writer.json；先跑一次全流程再使用）
./run.sh --browser --sections "experiments,results,conclusion"

# 研究偏好：更专注 system 方向（系统、架构、算法、性能），减少与兴趣无关的 idea
./run.sh --browser --focus system
# 或在 input.md 中写 Focus: system

# 人工干预（Explore 阶段选 idea，DeepResearch/Experiment/Writer 多轮确认）
./run.sh --browser --human
# 会生成 artifacts/review/ 下中文 Markdown 报告，终端提示选择编号或 y/n 继续下一阶段

# 长时间任务（后台运行）；控制请求频率避免限流（默认两次调用间隔 5 秒，可设 EFFICIENT_RESEARCH_BROWSER_MIN_INTERVAL=10）
nohup ./run.sh input.md --browser --thinking > run.log 2>&1 &
```

或直接调用 pipeline（适合调试）：
```bash
python -m orchestrator.pipeline --topic "你的研究主题" --venue "Workshop, 4-6 pages" --browser
python -m orchestrator.pipeline --topic "..." --venue "..." --sections "experiments,results,conclusion"
```

---

## 长期记忆（本地 RAG）

每次完整 run 结束后会自动将本 run 的摘要（假设、贡献、实验设计、写作片段等）写入**本地 RAG**（`artifacts/rag/`）。下次跑新 topic 或相关 topic 时，pipeline 会先按 topic 检索 RAG，把相关历史片段注入 Ideator，便于「在已有积累上整理与优化」。

- **依赖**：`pip install chromadb sentence-transformers`（见 `requirements.txt`）。
- **环境变量**：`EFFICIENT_RESEARCH_RAG_DIR` 可指定 RAG 持久化目录（默认 `artifacts/rag`）。
- **手动索引**：若希望把某次已有 run 纳入 RAG，可调用 `from tools.rag import index_run_artifacts; index_run_artifacts("artifacts/runs")`。

---

## 人工干预（--human）

使用 `./run.sh --human` 或 `python -m orchestrator.pipeline --topic "..." --venue "..." --human` 时：

1. **Ideator 之后**：在 `artifacts/review/01_ideator_报告.md` 生成中文报告（相关工作、潜在问题、潜在方向、提案的 motivation/idea/挑战）。终端打印编号与 idea 名称，**输入编号选择**（如 `1` 或 `1,3`），仅对选中的方向做 DeepResearch。
2. **DeepResearch**：每轮结果写入 `artifacts/review/03_deep_research_第N轮.md`。每轮结束后提示：**可编辑该 Markdown**，然后输入 **y** 再跑一轮、**n** 进入下一阶段（Skeptic/Review）。
3. **Experimenter 之后**：报告写入 `05_experimenter_报告.md`，提示 y 重新跑实验设计 / n 进入 Writer。
4. **Writer 每版之后**：报告写入 `06_writer_报告.md`，提示 y 再写一版 / n 进入 Editor。

所有报告为中文，便于直接编辑后由人类决定是否继续或进入下一阶段。

---

## 输出产物

```
artifacts/
├── review/                  # --human 时：中文 Markdown 报告（Ideator/DeepResearch/Experimenter/Writer）
├── paper/
│   ├── main.tex          # LaTeX 论文（IEEEtran 双列格式）
│   └── references.bib    # 参考文献
└── runs/
    ├── 01_ideator.json
    ├── 02_scout.json
    ├── 03_deep_research[_iterN].json   # 多轮时取最新迭代加载
    ├── 04_skeptic[_iterN].json
    ├── 05_experimenter[_iterN].json
    ├── 06_writer.json / 06_writer[_iterN].json   # partial 重写时优先加载 06_writer.json
    └── 07_editor.json
```

迭代发生时，文件名加 `_iter2` 等后缀，保留完整历史。`state["loop_log"]` 记录所有回环原因。

---

## 可审计性：声明标注

论文中每个可被质疑的声明必须携带以下标签之一：

| 标签 | 含义 |
|---|---|
| `[CITE:key]` | 引用 annotated_bib 中的文献 |
| `[EVID:exp_1]` | 引用 Experimenter 的主实验结果 |
| `[EVID:ablation_1]` | 引用消融实验结果 |
| `[SPEC]` | 推测性声明，无引用/实验支撑 |

---

## 质量门（`eval/gates.py`）

5 个质量门在 Writer 和 Editor 阶段运行，失败时触发对应回环：

| 门卡 | 检查内容 | 阈值 |
|---|---|---|
| `citation_coverage` | intro/related_work 中已标注声明占比 | ≥ 80% |
| `speculation_ratio` | intro/method 中 `[SPEC]` 占比 | ≤ 20% |
| `baseline_checklist` | DeepResearcher 提供的基线数量 | ≥ 1 |
| `skeptic_items_closed` | Writer 正文中提及的 Skeptic 条目占比 | ≥ 50% |
| `experiment_evidence_coverage` | results/experiments 中 `[EVID:]` 标签密度 | ≥ 50%×实验数 |

---

## Agent Skill 提示

每个 Agent 的系统提示存放在 `skills/<name>/SKILL.md`，可直接编辑调整行为。

也支持使用外部 [AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs)：
```bash
export EFFICIENT_RESEARCH_AI_RESEARCH_SKILLS=/path/to/AI-Research-SKILLs
```

---

## 搜索后端（`tools/search.py`）

| `source=` | 数据源 | 用途 |
|---|---|---|
| `"arxiv"` | ArXiv API（无需 key） | 论文查询（Scout/DeepResearcher 默认） |
| `"ss"` | Semantic Scholar（免费 REST API） | 引用数/结构化摘要 |
| `"web"` | DuckDuckGo | 博客、Survey |
| `"auto"` | 先 ArXiv，fallback Web | 默认 |

---

## 项目结构

```
EfficientResearch/
├── agents/          # 7 个 Agent（ideator, scout, deep_researcher, skeptic,
│                    #             experimenter, writer, editor）
├── orchestrator/    # pipeline.py（迭代主流程）+ state.py（共享状态）
├── tools/           # llm.py, search.py, latex_builder.py, citations.py,
│                    # io.py, skills_loader.py
├── eval/            # gates.py（5 个质量门）
├── skills/          # 每个 Agent 的 SKILL.md 系统提示
├── config.py        # LLM 配置（OpenAI / vLLM）
├── input.md         # 研究输入（Topic + Problem + Venue）
├── run.sh           # 主执行入口
├── env_prepare.sh   # 本地 vLLM 环境准备（Qwen3.5-9B）
└── requirements.txt
```
