# EfficientResearch Skills

本目录为 **本地 skills**（OpenClaw/NanoClaw 风格）：每个 agent 对应 `skills/<name>/SKILL.md`，含 YAML frontmatter + 正文（system prompt）。

## 与 AI-Research-SKILLs 的关系

**Research 相关能力优先使用 [Orchestra Research 的 AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs)**，该库提供 85+ 标准化 research 技能（ideation、ML paper writing、evaluation 等）。本 pipeline 会从该库**拉取**以下技能并在末尾追加本系统的 JSON 输出约定：

| 本 pipeline agent | AI-Research-SKILLs 路径 |
|-------------------|--------------------------|
| **ideator**       | `21-research-ideation/brainstorming-research-ideas/SKILL.md` |
| **writer**        | `20-ml-paper-writing/SKILL.md` |
| **editor**        | `20-ml-paper-writing/SKILL.md` |
| scout / deep_researcher / skeptic | 仅用本目录（该库无直接对应技能） |

### 如何使用 AI-Research-SKILLs

1. **拉取仓库**（推荐）：
   ```bash
   ./scripts/sync_ai_research_skills.sh
   # 默认克隆到 external/AI-Research-SKILLs
   ```

2. **设置环境变量**（在运行 `run.sh` 或 pipeline 前）：
   ```bash
   export EFFICIENT_RESEARCH_AI_RESEARCH_SKILLS=/path/to/AI-Research-SKILLs
   ```

3. 之后 ideator / writer / editor 会使用上述路径中的 SKILL.md 内容，并自动追加本 pipeline 要求的 JSON 输出格式。

未设置该变量时，仅使用本目录下的 `skills/<name>/SKILL.md`。

## 本地 skill 列表

- **ideator** — 生成可证伪假设（有映射时用 AI-Research-SKILLs 的 Research Brainstorming）
- **scout** — 文献探索与筛选（依赖网络搜索）
- **deep_researcher** — 注释书目与证据（依赖网络搜索）
- **skeptic** — 审稿式批评
- **writer** — LaTeX 初稿（有映射时用 AI-Research-SKILLs 的 ML Paper Writing）
- **editor** — 润色（有映射时同上）

修改某 agent 行为时，可编辑对应 `skills/<name>/SKILL.md`；若使用 AI-Research-SKILLs，可先拉取最新再设置 `EFFICIENT_RESEARCH_AI_RESEARCH_SKILLS`。
