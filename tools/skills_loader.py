"""
Skills loader: 优先使用 [AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs)，
其次本地 skills/<name>/SKILL.md。与 OpenClaw/NanoClaw 风格一致；使用外部 skill 时会追加本 pipeline 的 JSON 输出约定。
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_SKILLS_DIR: Optional[Path] = None

# 本 pipeline 的 agent 名 → AI-Research-SKILLs 相对路径（仅 research 相关有映射）
AI_RESEARCH_SKILLS_MAP = {
    "ideator": "21-research-ideation/brainstorming-research-ideas/SKILL.md",
    "writer": "20-ml-paper-writing/SKILL.md",
    "editor": "20-ml-paper-writing/SKILL.md",
    # scout, deep_researcher, skeptic 无直接对应，用本地 skills
}

# 使用外部 skill 时追加的「必须输出 JSON」约定，保证 pipeline 能解析
PIPELINE_OUTPUT_APPENDIX = {
    "ideator": """

## EfficientResearch pipeline output (mandatory)

Return a single JSON object with key "hypotheses", value an array of objects. Each object must have: id, claim, falsifiable_test, minimal_experiment, expected_gain, risks. No other top-level keys. No markdown outside the JSON.""",
    "writer": """

## EfficientResearch pipeline output (mandatory)

Output a JSON object with key "sections", value object with keys: abstract, intro, background, method, experiments, results, related_work, limitations, conclusion. Each value is LaTeX body. Tag claims with [CITE:key], [EVID:run_id], or [SPEC]. No markdown outside the JSON.""",
    "editor": """

## EfficientResearch pipeline output (mandatory)

Output the same JSON structure: key "sections", object with abstract, intro, background, method, experiments, results, related_work, limitations, conclusion. Preserve all [CITE:...], [EVID:...], [SPEC] tags. No markdown outside the JSON.""",
}

def get_ai_research_skills_root() -> Optional[Path]:
    """AI-Research-SKILLs 仓库根目录，由环境变量指定。"""
    path = os.environ.get("EFFICIENT_RESEARCH_AI_RESEARCH_SKILLS", "").strip()
    if not path:
        return None
    p = Path(path).expanduser().resolve()
    return p if p.is_dir() else None

def get_skills_dir() -> Path:
    global _SKILLS_DIR
    if _SKILLS_DIR is None:
        _SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
    return _SKILLS_DIR

def _parse_skill_md(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse SKILL.md: YAML frontmatter between --- ... ---, then body."""
    frontmatter: Dict[str, Any] = {}
    body = content.strip()
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", body, re.DOTALL)
    if match:
        try:
            import yaml
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except Exception:
            pass
        body = match.group(2).strip()
    return frontmatter, body

def _read_external_skill(root: Path, relative_path: str) -> Optional[str]:
    path = root / relative_path
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None

def get_skill(skill_name: str) -> Dict[str, Any]:
    """
    Load skill by name. 优先 AI-Research-SKILLs → skills/<name>/SKILL.md.
    Returns {"name", "description", "inputs", "outputs", "instruction"}.
    """
    root_external = get_ai_research_skills_root()
    relative = AI_RESEARCH_SKILLS_MAP.get(skill_name)
    if root_external and relative:
        raw = _read_external_skill(root_external, relative)
        if raw:
            front, body = _parse_skill_md(raw)
            appendix = PIPELINE_OUTPUT_APPENDIX.get(skill_name, "")
            if appendix:
                body = body.rstrip() + "\n" + appendix.strip()
            return {
                "name": front.get("name", skill_name),
                "description": front.get("description", ""),
                "inputs": front.get("inputs", ""),
                "outputs": front.get("outputs", ""),
                "instruction": body,
            }

    skills_dir = get_skills_dir()
    path = skills_dir / skill_name / "SKILL.md"
    if not path.exists():
        return {"name": skill_name, "description": "", "instruction": f"[Skill {skill_name} not found at {path}]"}
    content = path.read_text(encoding="utf-8")
    front, body = _parse_skill_md(content)
    return {
        "name": front.get("name", skill_name),
        "description": front.get("description", ""),
        "inputs": front.get("inputs", ""),
        "outputs": front.get("outputs", ""),
        "instruction": body,
    }

def get_skill_prompt(skill_name: str) -> str:
    """Return the instruction text for an agent (system prompt)."""
    skill = get_skill(skill_name)
    instruction = skill.get("instruction", "").strip()
    if instruction and not instruction.startswith("[Skill ") and "[not found" not in instruction:
        return instruction
    return instruction or f"[Empty skill: {skill_name}; add skills/{skill_name}/SKILL.md or set EFFICIENT_RESEARCH_AI_RESEARCH_SKILLS]"

def list_skills() -> list:
    """Return names of installed skills (local skills/ that contain SKILL.md)."""
    skills_dir = get_skills_dir()
    if not skills_dir.exists():
        return []
    return [d.name for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
