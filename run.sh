#!/usr/bin/env bash
# run.sh: 从 input.md 读取 research topic，启动 multi-agent 协作与探索
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_FILE=""
VENV_DIR="${SCRIPT_DIR}/../auto-paper-reading/venv"
USE_LOCAL=""

# 解析可选参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)
      USE_LOCAL="--local"
      shift
      ;;
    -i|--input)
      INPUT_FILE="$2"
      shift 2
      ;;
    -*)
      echo "未知选项: $1"
      exit 1
      ;;
    *)
      INPUT_FILE="$1"
      shift
      ;;
  esac
done
# 未指定输入文件时使用仓库内 input.md（支持 bash run.sh --local）
if [[ -z "$INPUT_FILE" ]]; then
  INPUT_FILE="${SCRIPT_DIR}/input.md"
else
  # 相对路径时基于当前目录解析
  [[ "$INPUT_FILE" != /* ]] && [[ -f "$INPUT_FILE" ]] && INPUT_FILE="$(cd "$(dirname "$INPUT_FILE")" && pwd)/$(basename "$INPUT_FILE")"
fi

if [[ ! -f "$INPUT_FILE" ]]; then
  echo "错误: 输入文件不存在: $INPUT_FILE"
  echo "用法: $0 [input.md] [--local]"
  echo "      或: $0 --input input.md --local"
  echo ""
  echo "请创建 input.md 并填写要研究的 topic，例如："
  echo "  Topic: OOD-aware graph-based ANNS for multimodal retrieval"
  echo "  Venue: Workshop, 4-6 pages, double-column"
  exit 1
fi

# 从 input.md 解析 Topic / Venue（兼容多行与单行）
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
  # 回退：取第一个非空非标题行作为 topic
  TOPIC=$(grep -v '^[[:space:]]*#' "$INPUT_FILE" | grep -v '^[[:space:]]*$' | head -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
fi
VENUE=$(parse_field "Venue" "$INPUT_FILE")
if [[ -z "$VENUE" ]]; then
  VENUE="Workshop, 4-6 pages, double-column"
fi
CONSTRAINTS=$(parse_field "Constraints" "$INPUT_FILE")

if [[ -z "$TOPIC" ]]; then
  echo "错误: 未在 $INPUT_FILE 中找到 Topic。请填写例如："
  echo "  Topic: 你的研究主题"
  exit 1
fi

echo "=============================================="
echo "  EfficientResearch · Multi-Agent 协作"
echo "=============================================="
echo "  输入文件: $INPUT_FILE"
echo "  Topic:    $TOPIC"
echo "  Venue:    $VENUE"
[[ -n "$CONSTRAINTS" ]] && echo "  Constraints: $CONSTRAINTS"
LOCAL_LABEL="否"
[ -n "$USE_LOCAL" ] && LOCAL_LABEL="是 (--local)"
echo "  本地模型: $LOCAL_LABEL"
echo "=============================================="

# 使用与 env_prepare 一致的虚拟环境
if [[ -d "$VENV_DIR" ]]; then
  source "${VENV_DIR}/bin/activate"
else
  echo "提示: 未找到虚拟环境 $VENV_DIR，使用当前 Python。如需本地模型请先执行 ./env_prepare.sh"
fi

# --local 时预检本地 LLM 是否可达
if [[ -n "$USE_LOCAL" ]]; then
  LLM_URL="${OPENAI_BASE_URL:-http://127.0.0.1:8000/v1}"
  BASE="${LLM_URL%/v1*}"
  if ! curl -sf -o /dev/null --connect-timeout 3 "${BASE}/health" 2>/dev/null && ! curl -sf -o /dev/null --connect-timeout 3 "${BASE}/v1/models" 2>/dev/null; then
    echo "错误: 本地 LLM 服务未就绪 (无法连接 ${BASE})。"
    echo "请先启动 vLLM，例如: ./env_prepare.sh 或 在另一终端运行 vllm serve <model_path> --port 8000"
    exit 1
  fi
fi

cd "$SCRIPT_DIR"
CMD=(python3 -m orchestrator.pipeline --topic "$TOPIC" --venue "$VENUE")
[[ -n "$CONSTRAINTS" ]] && CMD+=(--constraints "$CONSTRAINTS")
[[ -n "$USE_LOCAL" ]] && CMD+=(--local)
"${CMD[@]}"

echo ""
echo "完成。可在 artifacts/paper/ 查看 LaTeX 稿, artifacts/runs/ 查看各阶段结果。"
