#!/usr/bin/env bash
# env_prepare.sh: 虚拟环境创建 + 依赖安装 + ModelScope 拉取 Qwen3.5-9B + vLLM 部署 + 探活检测
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# VENV_DIR="${SCRIPT_DIR}/venv"
# MODELS_DIR="${SCRIPT_DIR}/Models"
VENV_DIR="${SCRIPT_DIR}/../auto-paper-reading/venv"
MODELS_DIR="${SCRIPT_DIR}/../auto-paper-reading/Models"
MODEL_NAME="Qwen3.5-9B"
MODEL_ID="Qwen/Qwen3.5-9B"
VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_HOST="${VLLM_HOST:-0.0.0.0}"

echo "[1/5] 创建虚拟环境: ${VENV_DIR}"
mkdir -p "$(dirname "$VENV_DIR")"
if [[ -d "$VENV_DIR" ]]; then
  echo "      虚拟环境已存在，跳过创建"
else
  python3 -m venv "$VENV_DIR"
fi
source "${VENV_DIR}/bin/activate"

echo "[2/5] 安装依赖"
pip install -q -U pip
pip install -q -r "${SCRIPT_DIR}/requirements.txt"
pip install -q vllm modelscope

echo "[3/5] ModelScope 下载模型: ${MODEL_ID} -> ${MODELS_DIR}/${MODEL_NAME}"
mkdir -p "$MODELS_DIR"
export MS_MODEL_ID="$MODEL_ID" MS_MODELS_DIR="$MODELS_DIR" MS_MODEL_NAME="$MODEL_NAME"
python3 -c "
from modelscope import snapshot_download
import os
model_id = os.environ.get('MS_MODEL_ID', 'Qwen/Qwen3.5-9B')
models_dir = os.environ.get('MS_MODELS_DIR', '.')
model_name = os.environ.get('MS_MODEL_NAME', 'Qwen3.5-9B')
local_dir = os.path.join(models_dir, model_name)
os.makedirs(models_dir, exist_ok=True)
snapshot_download(model_id, local_dir=local_dir)
print('Downloaded to:', local_dir)
"

echo "[4/5] 启动 vLLM 服务 (port=${VLLM_PORT})"
MODEL_PATH="${MODELS_DIR}/${MODEL_NAME}"
if [[ ! -d "$MODEL_PATH" ]]; then
  echo "错误: 模型目录不存在 $MODEL_PATH"
  exit 1
fi
# 后台启动 vLLM（OpenAI 兼容 API）
pkill -f "vllm.entrypoints.openai.api_server" 2>/dev/null || true
sleep 2
nohup python3 -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" \
  --host "$VLLM_HOST" \
  --port "$VLLM_PORT" \
  --served-model-name "$MODEL_NAME" \
  >> "${SCRIPT_DIR}/../auto-paper-reading/vllm.log" 2>&1 &
echo "      vLLM 后台启动，日志: ../auto-paper-reading/vllm.log"
sleep 3

echo "[5/5] 探活检测"
BASE_URL="http://127.0.0.1:${VLLM_PORT}"
HEALTH_URL="${BASE_URL}/health"
V1_URL="${BASE_URL}/v1/models"
max_attempts=120
attempt=0
while [[ $attempt -lt $max_attempts ]]; do
  if curl -sf -o /dev/null "${HEALTH_URL}" 2>/dev/null; then
    echo "      /health 正常"
    break
  fi
  if curl -sf -o /dev/null "${V1_URL}" 2>/dev/null; then
    echo "      /v1/models 可访问"
    break
  fi
  attempt=$((attempt + 1))
  echo "      等待服务就绪... (${attempt}/${max_attempts})"
  sleep 5
done
if [[ $attempt -ge $max_attempts ]]; then
  echo "警告: 探活超时，请检查 ${HEALTH_URL} 或 ${V1_URL} 与日志: ../auto-paper-reading/vllm.log"
  exit 1
fi
echo "      vLLM 已就绪: ${BASE_URL}/v1"

echo ""
echo "完成. 使用本地模型时请设置:"
echo "  export EFFICIENT_RESEARCH_LLM=local"
echo "  export OPENAI_BASE_URL=http://127.0.0.1:${VLLM_PORT}/v1"
echo "  export EFFICIENT_RESEARCH_MODEL=${MODEL_NAME}"
