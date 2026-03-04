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
| **Experimenter** | 设计实验方案，生成 Python 代码框架，产出模拟结果表 | `experiment_plan`, `code_snippets`, `result_tables` |
| **Writer** | 基于上述全部产出写 LaTeX 论文（9 章节） | `sections` dict |
| **Editor** | 润色学术语气，保留所有标注标签 | 改进后的 `sections` |

**迭代回环：**
- Skeptic 发现 ≥3 条证据缺口 → DeepResearcher 用 `rejection_risks` 作为精准搜索词重新检索
- Writer 质量门失败（引用/基线不足）→ 回到 DeepResearcher + Skeptic
- Writer 质量门失败（实验覆盖不足）→ 回到 Experimenter
- Writer 质量门失败（过度推测）→ Writer 带 `fix_list` 自我修正

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

```markdown
Topic: 你的研究主题（中英文均可）

## Problem
- 背景和现状描述
- 核心问题

Venue: Workshop, 4-6 pages, double-column
```

### 4. 运行

```bash
./run.sh                    # 读取 input.md，使用 OpenAI API
./run.sh --local            # 使用本地 vLLM
./run.sh --input my.md      # 指定其他输入文件
```

或直接调用 pipeline（适合调试）：
```bash
python -m orchestrator.pipeline \
  --topic "你的研究主题" \
  --venue "Workshop, 4-6 pages, double-column"
```

---

## 输出产物

```
artifacts/
├── paper/
│   ├── main.tex          # LaTeX 论文（IEEEtran 双列格式）
│   └── references.bib    # 参考文献
└── runs/
    ├── 01_ideator.json
    ├── 02_scout.json
    ├── 03_deep_research[_iterN].json
    ├── 04_skeptic[_iterN].json
    ├── 05_experimenter[_iterN].json
    ├── 06_writer[_iterN].json
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
