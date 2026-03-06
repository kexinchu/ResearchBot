#!/usr/bin/env bash
# run.sh: Read research topic from input.md, start multi-agent pipeline.
# Long-running task — use nohup or tmux:
#   nohup ./run.sh input.md --browser > run.log 2>&1 &
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_FILE=""
VENV_DIR="${SCRIPT_DIR}/venv"
USE_BROWSER=""
USE_THINKING=""
SECTIONS_ARG=""
FOCUS_ARG=""
USE_RESUME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --browser)
      USE_BROWSER="--browser"
      shift
      ;;
    --thinking)
      USE_THINKING="1"
      shift
      ;;
    -i|--input)
      INPUT_FILE="$2"
      shift 2
      ;;
    --sections)
      SECTIONS_ARG="$2"
      shift 2
      ;;
    --focus)
      FOCUS_ARG="$2"
      shift 2
      ;;
    --resume)
      USE_RESUME=1
      shift
      ;;
    -*)
      echo "Unknown option: $1"
      exit 1
      ;;
    *)
      INPUT_FILE="$1"
      shift
      ;;
  esac
done

if [[ -z "$INPUT_FILE" ]]; then
  INPUT_FILE="${SCRIPT_DIR}/input.md"
else
  [[ "$INPUT_FILE" != /* ]] && [[ -f "$INPUT_FILE" ]] && INPUT_FILE="$(cd "$(dirname "$INPUT_FILE")" && pwd)/$(basename "$INPUT_FILE")"
fi

if [[ ! -f "$INPUT_FILE" ]]; then
  echo "Error: input file not found: $INPUT_FILE"
  echo "Usage: $0 [input.md] [--browser] [--thinking] [--sections 'a,b,c']"
  echo "       or: $0 --input input.md --browser"
  echo ""
  echo "Create input.md with your research topic, e.g.:"
  echo "  Topic: OOD-aware graph-based ANNS for multimodal retrieval"
  echo "  Venue: Workshop, 4-6 pages, double-column"
  echo "  (optional) Sections: experiments,results,conclusion"
  echo "  (optional) Focus: system"
  exit 1
fi

# Parse Topic / Venue from input.md
parse_field() {
  local key="$1"
  local file="$2"
  local in_block=0
  local result=""
  while IFS= read -r line; do
    if [[ "$line" =~ ^[#]*[[:space:]]*${key}[[:space:]]*:[[:space:]]*(.*) ]]; then
      result="${BASH_REMATCH[1]}"
      in_block=1
      continue
    fi
    if [[ $in_block -eq 1 ]]; then
      if [[ "$line" =~ ^[[:space:]]*$ ]]; then
        break
      fi
      if [[ "$line" =~ ^[#]*[[:space:]]*[A-Za-z]+[[:space:]]*: ]]; then
        break
      fi
      result="${result} ${line}"
    fi
  done < "$file"
  echo "$result" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

TOPIC=$(parse_field "Topic" "$INPUT_FILE")
if [[ -z "$TOPIC" ]]; then
  TOPIC=$(grep -v '^[[:space:]]*#' "$INPUT_FILE" | grep -v '^[[:space:]]*$' | head -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
fi
VENUE=$(parse_field "Venue" "$INPUT_FILE")
if [[ -z "$VENUE" ]]; then
  VENUE="Workshop, 4-6 pages, double-column"
fi
CONSTRAINTS=$(parse_field "Constraints" "$INPUT_FILE")
INPUT_SECTIONS=$(parse_field "Sections" "$INPUT_FILE")
INPUT_THINKING=$(parse_field "Thinking" "$INPUT_FILE")
INPUT_FOCUS=$(parse_field "Focus" "$INPUT_FILE")
[[ -z "$SECTIONS_ARG" && -n "$INPUT_SECTIONS" ]] && SECTIONS_ARG="$INPUT_SECTIONS"
[[ -z "$USE_THINKING" && -n "$INPUT_THINKING" ]] && USE_THINKING="$INPUT_THINKING"
[[ -z "$FOCUS_ARG" && -n "$INPUT_FOCUS" ]] && FOCUS_ARG="$INPUT_FOCUS"

if [[ -z "$TOPIC" ]]; then
  echo "Error: no Topic found in $INPUT_FILE."
  echo "  Topic: your research topic"
  exit 1
fi

echo "=============================================="
echo "  EfficientResearch - Multi-Agent Pipeline"
echo "=============================================="
echo "  Input:    $INPUT_FILE"
echo "  Topic:    $TOPIC"
echo "  Venue:    $VENUE"
[[ -n "$CONSTRAINTS" ]] && echo "  Constraints: $CONSTRAINTS"
[[ -n "$SECTIONS_ARG" ]] && echo "  Sections: $SECTIONS_ARG"
[[ -n "$FOCUS_ARG" ]] && echo "  Focus: $FOCUS_ARG"
echo "  Human-in-the-loop: ON (default)"
MODE_LABEL="API"
[ -n "$USE_BROWSER" ] && MODE_LABEL="Browser (Playwright)"
echo "  LLM mode: $MODE_LABEL"
[ -n "$USE_THINKING" ] && echo "  Thinking: ON"
echo "=============================================="

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Error: venv not found at $VENV_DIR"
  echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
source "${VENV_DIR}/bin/activate"

cd "$SCRIPT_DIR"
[[ -n "$USE_THINKING" ]] && export EFFICIENT_RESEARCH_BROWSER_THINKING=1
CMD=(python3 -m orchestrator.pipeline --topic "$TOPIC" --venue "$VENUE")
[[ -n "$CONSTRAINTS" ]] && CMD+=(--constraints "$CONSTRAINTS")
[[ -n "$USE_BROWSER" ]] && CMD+=(--browser)
[[ -n "$SECTIONS_ARG" ]] && CMD+=(--sections "$SECTIONS_ARG")
[[ -n "$FOCUS_ARG" ]] && CMD+=(--focus "$FOCUS_ARG")
[[ -n "$USE_RESUME" ]] && CMD+=(--resume)
"${CMD[@]}"

echo ""
echo "Done. Check artifacts/paper/ for LaTeX, artifacts/runs/ for stage results."
