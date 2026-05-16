#!/bin/sh
set -eu

BASE_MODEL="${FREE_LLM_BASE_MODEL:-qwen2.5:1.5b}"
MODEL_NAME="${FREE_LLM_MODEL_NAME:-agent-free-qwen}"
NUM_CTX="${FREE_LLM_NUM_CTX:-8192}"
TEMPERATURE="${FREE_LLM_TEMPERATURE:-0.2}"

echo "[free-llm] Starting Ollama server..."
/bin/ollama serve &
OLLAMA_PID=$!

cleanup() {
  echo "[free-llm] Stopping Ollama server..."
  kill "$OLLAMA_PID" >/dev/null 2>&1 || true
  wait "$OLLAMA_PID" >/dev/null 2>&1 || true
}

trap cleanup INT TERM

echo "[free-llm] Waiting for Ollama API to become ready..."
until ollama list >/dev/null 2>&1; do
  sleep 2
done

echo "[free-llm] Ensuring base model is available: ${BASE_MODEL}"
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fx "${BASE_MODEL}" >/dev/null 2>&1; then
  ollama pull "${BASE_MODEL}"
fi

echo "[free-llm] Ensuring runtime model alias exists: ${MODEL_NAME}"
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fx "${MODEL_NAME}" >/dev/null 2>&1; then
  cat >/tmp/Modelfile <<EOF
FROM ${BASE_MODEL}
PARAMETER num_ctx ${NUM_CTX}
PARAMETER temperature ${TEMPERATURE}
EOF
  ollama create "${MODEL_NAME}" -f /tmp/Modelfile
fi

echo "[free-llm] Ready. OpenAI-compatible API at /v1 with model ${MODEL_NAME}"
wait "$OLLAMA_PID"
