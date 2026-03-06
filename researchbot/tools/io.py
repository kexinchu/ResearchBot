"""IO: load/save artifacts with validation."""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

def load_json(path: str | Path) -> Any:
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(data: Any, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_yaml(path: str | Path) -> Any:
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML required for YAML: pip install pyyaml")
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml(data: Any, path: str | Path) -> None:
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML required for YAML: pip install pyyaml")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

def ensure_artifacts_dirs(artifacts_root: str | Path) -> Dict[str, Path]:
    root = Path(artifacts_root)
    dirs = {
        "library": root / "library",
        "runs": root / "runs",
        "paper": root / "paper",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def load_state_from_runs(runs_dir: str | Path) -> Optional[Dict[str, Any]]:
    """Load pipeline state from existing run JSONs (01_ideator .. 05_experimenter, 06_writer).
    Returns None if any required file is missing."""
    runs = Path(runs_dir)
    state = {}
    for name in ["01_ideator", "02_scout", "03_deep_research", "04_skeptic", "05_experimenter"]:
        # accept 03_deep_research_iter2 etc.; take latest by filename sort so we get latest iteration
        candidates = sorted(runs.glob(name + "*.json"))
        if not candidates:
            return None
        data = load_json(candidates[-1])
        if data is None:
            return None
        state.update(data)
    # optional: writer output for partial rewrite — prefer full run (06_writer.json) over partial save
    canonical_writer = runs / "06_writer.json"
    if canonical_writer.exists():
        data = load_json(canonical_writer)
        if data and data.get("writer_output"):
            state["writer_output"] = data["writer_output"]
    else:
        writer_jsons = sorted(runs.glob("06_writer*.json"))
        if writer_jsons:
            data = load_json(writer_jsons[-1])
            if data and data.get("writer_output"):
                state["writer_output"] = data["writer_output"]
    return state
