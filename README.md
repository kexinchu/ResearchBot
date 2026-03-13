# ResearchBot

Research assistant toolkit for paper management, idea exploration, experiment design, and knowledge organization. Built around **Zotero** (canonical paper library) + **Obsidian** (editable note layer) with local-first RAG for context retrieval.

---

## Commands

```bash
researchbot init                   # Generate config.yaml template
researchbot record <url>           # Record a paper → Zotero + Obsidian
researchbot note [--type idea]     # Create a structured note → Obsidian
researchbot explore <topic>        # Deep research exploration → report
researchbot experiment <idea>      # Quick experiment design → code scaffolds
researchbot index                  # Index Obsidian vault into RAG

# for cache within the session, can open/close an session 
researchbot browser start
researchbot browser new    # create new session
researchbot browser stop
```

---

## Installation

Requires **Python 3.10+**.

```bash
git clone https://github.com/your-repo/ResearchBot.git
cd ResearchBot
pip install -e .

# With local RAG (ChromaDB + sentence-transformers)
pip install -e ".[rag]"

# With browser mode (ChatGPT web UI, no API key needed)
pip install -e ".[browser]"
playwright install chromium

# Everything
pip install -e ".[all]"
```

---

## Quick Start

```bash
# 1. Generate config file (either way works)
researchbot init                      # generates config.yaml in current directory
# OR: copy the example template
cp config.yaml.example config.yaml

# 2. Edit config.yaml — fill in your API keys and paths (see below)

# 3. Start using
researchbot record https://arxiv.org/abs/2406.12385
```

---

## Configuration

All configuration is in **`config.yaml`**. Environment variables also work and take precedence over config.yaml.

```bash
# Generate config template in current directory
researchbot init

# Or generate in ~/.researchbot/ (global, shared across projects)
researchbot init --global
```

Config file search order:
1. `./config.yaml` (project-local)
2. `~/.researchbot/config.yaml` (user-global)

### 1. LLM (required)

You need an LLM API to generate reading notes, classify papers, and run explore/experiment.

```yaml
llm:
  api_key: "sk-..."               # Your OpenAI API key
  base_url: ""                     # Leave empty for OpenAI; set for other providers
  model: "gpt-4o-mini"            # Model to use
```

**How to get your API key:**
- **OpenAI**: Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → "Create new secret key"
- **DeepSeek**: Go to [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) → create key, set `base_url: "https://api.deepseek.com/v1"` and `model: "deepseek-chat"`
- **Local vLLM/Ollama**: Set `base_url: "http://localhost:8000/v1"` (or your local port), `api_key: "not-needed"`
- **Browser mode** (no key needed): Use `--browser` flag on commands — it automates ChatGPT web UI via Playwright

### 2. Obsidian (required)

Point to your Obsidian vault folder — this is where all notes are written.

```yaml
obsidian:
  vault_path: "~/ObsidianVault"   # Absolute path to your vault
```

**How to find your vault path:**
1. Open Obsidian
2. Click the vault name (bottom-left) → "Manage vaults"
3. The path is shown next to your vault name
4. Or: your vault is just a regular folder — find it in Finder/Explorer

ResearchBot auto-creates this structure inside your vault:

```
<vault>/
├── Papers-ANNS/             # Paper reading notes (by type)
├── Papers-RAG/
├── Papers-LLM-Opt/
├── Papers-KV-Cache/
├── Papers-.../
├── Papers-Other/
├── Idea/                    # Research ideas
└── Explore/                 # Exploration reports
```

### 3. Zotero (optional, recommended)

Zotero stores your paper library with PDF attachments. If not configured, `researchbot record` still works — it just skips Zotero.

```yaml
zotero:
  api_key: ""                      # Your Zotero API key
  library_id: ""                   # Your Zotero user ID (numeric)
  library_type: "user"             # "user" or "group"
```

**How to get these values:**

1. **API key**: Go to [zotero.org/settings/keys](https://www.zotero.org/settings/keys) → "Create new private key"
   - Name: `ResearchBot` (or anything)
   - Check **"Allow library access"** → "Read/Write"
   - Check **"Allow write access"**
   - Save → copy the key string

2. **Library ID**: On the same page ([zotero.org/settings/keys](https://www.zotero.org/settings/keys)), look for **"Your userID for use in API calls is ..."** at the top. That number is your `library_id`.
   - Or: go to [zotero.org/settings/storage](https://www.zotero.org/settings/storage) → the number in the URL (`/users/<number>/...`) is your library ID

3. **Library type**: Use `"user"` for your personal library. Use `"group"` if you want to add papers to a group library (you'll need the group's numeric ID instead).

### 4. RAG (optional, recommended)

RAG enables semantic search across your paper notes during `explore` and `experiment`, so the LLM agents see your existing knowledge.

**Library**: [ChromaDB](https://www.trychroma.com/) (local vector database) + [sentence-transformers](https://www.sbert.net/) (embeddings).

```yaml
rag:
  dir: "~/.researchbot/rag"              # Where to store the vector index
  embedding_model: "all-MiniLM-L6-v2"    # sentence-transformers model
```

**Setup:**
```bash
# 1. Install RAG dependencies
pip install -e ".[rag]"

# 2. Index your existing Obsidian vault (run once, then re-run after manual edits)
researchbot index
```

After initial indexing, new notes are **automatically indexed** when created via `record` or `note`.

**How context retrieval works** (during `explore`/`experiment`):
1. **RAG**: semantic search across all indexed notes (fastest, most relevant)
2. **Zotero**: keyword search in your Zotero library (catches papers not yet in Obsidian)
3. **Obsidian**: direct file scan with keyword matching (fallback if RAG is not installed)

### 5. Paper Type Taxonomy (optional)

Customize how papers are classified. Default categories cover systems/ML research:

```yaml
paper_types:
  - ANNS
  - RAG
  - Diffusion-Language-Model
  - LLM-Opt
  - Agentic-OS
  - KV-Cache
  - LLM-Security
  - Memory
  - Deterministic-LLM
  - Other
```

Edit this list in `config.yaml` to add/remove categories. The classifier uses keyword matching + LLM to assign types. Papers are stored in `Papers-<type>/` folders (e.g., `Papers-ANNS/`, `Papers-KV-Cache/`).

### Full config.yaml example

```yaml
llm:
  api_key: "sk-proj-abc123..."
  base_url: ""
  model: "gpt-4o-mini"

zotero:
  api_key: "aB1cD2eF3gH4iJ5kL6"
  library_id: "12345678"
  library_type: "user"

obsidian:
  vault_path: "/Users/you/Documents/MyVault"

rag:
  dir: "~/.researchbot/rag"
  embedding_model: "all-MiniLM-L6-v2"

paper_types:
  - ANNS
  - RAG
  - Diffusion-Language-Model
  - LLM-Opt
  - Agentic-OS
  - KV-Cache
  - LLM-Security
  - Memory
  - Deterministic-LLM
  - Other
```

### Environment Variables (alternative)

Every config field can also be set via env var (takes precedence over config.yaml):

| Env Variable | config.yaml path | Default |
|---|---|---|
| `OPENAI_API_KEY` | `llm.api_key` | — |
| `OPENAI_BASE_URL` | `llm.base_url` | OpenAI default |
| `RESEARCHBOT_MODEL` | `llm.model` | `gpt-4o-mini` |
| `RESEARCHBOT_OBSIDIAN_VAULT` | `obsidian.vault_path` | `~/ObsidianVault` |
| `ZOTERO_API_KEY` | `zotero.api_key` | — |
| `ZOTERO_LIBRARY_ID` | `zotero.library_id` | — |
| `ZOTERO_LIBRARY_TYPE` | `zotero.library_type` | `user` |
| `RESEARCHBOT_RAG_DIR` | `rag.dir` | `~/.researchbot/rag/` |
| `RESEARCHBOT_RAG_EMBEDDING_MODEL` | `rag.embedding_model` | `all-MiniLM-L6-v2` |
| `RESEARCHBOT_PAPER_TYPES` | `paper_types` (comma-separated) | See defaults |
| `SS_API_KEY` | — | — (Semantic Scholar, optional) |

---

## Usage

### Record a paper

```bash
researchbot record https://arxiv.org/abs/2406.12385
researchbot record https://doi.org/10.1145/1234567
researchbot record https://arxiv.org/abs/2406.12385 --no-zotero
researchbot record https://arxiv.org/abs/2406.12385 --vault ~/MyVault
```

What happens:
1. Parses URL (arXiv, Semantic Scholar, DOI, generic)
2. Fetches metadata (title, authors, abstract, year, venue)
3. Checks Zotero for duplicates, adds if new (with PDF attachment)
4. Classifies paper type via keyword matching + LLM
5. Generates structured reading note (problem → importance → method [motivation/challenge/design] → results → summary → limitations → insights)
6. Writes to Obsidian: `Papers-<paper_type>/<title>.md`
7. Indexes into RAG

### Create a note

```bash
researchbot note                                    # interactive input
researchbot note --input my_thoughts.txt            # from file
researchbot note --type idea                        # force idea type
echo "What if we..." | researchbot note --type idea # from stdin
```

Auto-detects whether input is a paper note or research idea. Ideas go to `Idea/`, paper notes go to `Papers-<type>/`.

### Explore a research topic

```bash
researchbot explore "efficient LLM serving on heterogeneous GPU clusters"
researchbot explore "vector search indexing" --focus system
researchbot explore "RAG for code generation" --obsidian
researchbot explore "multi-agent coordination" --browser
```

Pipeline: **Context Retrieval → Ideator → DeepResearcher → Skeptic**

Output: `explore/<topic>.md` — hypotheses, gap analysis, annotated bibliography, skeptic review.

### Design experiments

```bash
researchbot experiment "Use HNSW with learned routing to reduce vector search latency by 2x"
researchbot experiment --obsidian
```

Output: `experiments/<idea>.md` — experiment plan, code scaffolds, expected result tables.

### Index vault into RAG

```bash
researchbot index                   # index default vault
researchbot index --vault ~/MyVault # index specific vault
```

---

## Obsidian Note Format

All notes use YAML frontmatter for machine-parsability and RAG indexing.

### Paper note (`Papers-<type>/<title>.md`)

```yaml
---
title: "Fast Graph Vector Search"
type: paper
paper_type: VectorSearch
authors:
  - Wenqi Jiang
  - Hang Hu
year: 2024
venue: "SIGMOD"
source_url: "https://arxiv.org/abs/2406.12385"
zotero_key: "ABC123"
tags:
  - vector-search
  - graph-index
  - hardware-acceleration
created_at: 2024-06-18
updated_at: 2024-06-18
---
# Fast Graph Vector Search
## Problem
## Importance
## Method
### Motivation
### Challenge
### Design
## Key Results
## Summary
## Limitations
## Insights for My Research
## Personal Notes
```

### Idea note (`Idea/<title>.md`)

```yaml
---
title: "Speculative Decoding on Heterogeneous GPUs"
type: idea
tags:
  - llm
  - inference
created_at: 2024-06-18
updated_at: 2024-06-18
---
# Speculative Decoding on Heterogeneous GPUs
## Hypothesis
## Motivation
## Related Directions
## Open Questions
## Next Steps
## Personal Notes
```

---

## Project Structure

```
researchbot/
├── cli.py                       # CLI: init, record, note, explore, experiment, index
├── config.py                    # config.yaml + env var loading
├── models.py                    # Data models (PaperMetadata, PaperNote, IdeaNote)
├── agents/                      # LLM agents
│   ├── ideator.py               # Hypothesis generation, gap analysis
│   ├── deep_researcher.py       # Literature search, annotated bibliography
│   ├── skeptic.py               # Adversarial review, feasibility challenge
│   └── experimenter.py          # Experiment design, code scaffolds
├── scholar/                     # Paper management
│   ├── url_parser.py            # URL parsing (arXiv, S2, DOI, generic)
│   ├── metadata.py              # Metadata fetching (arXiv API, Semantic Scholar)
│   ├── classifier.py            # Paper type classification (keywords + LLM)
│   ├── zotero_client.py         # Zotero integration (pyzotero)
│   ├── note_generator.py        # Structured note generation (LLM)
│   ├── obsidian_writer.py       # Obsidian vault writing
│   └── context_retriever.py     # Context retrieval (RAG + Zotero + Obsidian)
├── orchestrator/
│   ├── explore.py               # Explore pipeline
│   └── experiment.py            # Experiment pipeline
├── tools/
│   ├── llm.py                   # LLM calls (OpenAI-compatible, retry, cache)
│   ├── search.py                # ArXiv, Semantic Scholar, DuckDuckGo search
│   ├── rag.py                   # Local RAG (ChromaDB + sentence-transformers)
│   ├── io.py                    # File I/O (JSON, YAML, markdown)
│   ├── browser_llm.py           # Playwright-based ChatGPT automation
│   └── skills_loader.py         # SKILL.md prompt loader
└── skills/                      # Agent system prompts (SKILL.md files)
```

---

## Browser Mode

Uses Playwright to automate ChatGPT — no API key required.

```bash
researchbot explore "your topic" --browser
```

First run: a Chrome window opens — log in to ChatGPT manually. Session is reused within the same terminal.

To auto-login with cookies:
```bash
export EFFICIENT_RESEARCH_COOKIE_FILE="$HOME/cookies_chatgpt.json"
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OPENAI_API_KEY not set` | Set `llm.api_key` in config.yaml or `export OPENAI_API_KEY="sk-..."` |
| Zotero skipped | Set `zotero.api_key` and `zotero.library_id` in config.yaml |
| RAG not working | Run `pip install -e ".[rag]"` then `researchbot index` |
| Empty metadata | Check URL format; try arXiv abs URL instead of PDF |
| Browser mode CAPTCHA | Delete `~/.chatgpt-bot-profile` and re-login |
| Wrong paper classification | Edit `paper_types` in config.yaml, or edit the note manually |
