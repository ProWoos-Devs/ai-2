#!/bin/sh
# A/B: generation speed without and with self-speculative decoding (MTP head)
# on Qwen3.5 0.8B, on this machine's AI-2 runtime. Prints tokens/s for both.
#   curl -sL https://raw.githubusercontent.com/ProWoos-Devs/ai-2/main/tools/spec-ab.sh | sh
set -u
MODEL_ID=qwen3.5-0.8b
FILE=Qwen3.5-0.8B-Q4_K_M.gguf
PORT=8099
ai-2 model pull $MODEL_ID || exit 1
ai-2 stop >/dev/null 2>&1
M=$(find "$HOME/.local/share/ai2/models" /var/lib/ai2/models -name "$FILE" 2>/dev/null | head -1)
R=$(dirname "$(ls /usr/lib/ai2/runtimes/*/llama-server 2>/dev/null | head -1)")
[ -n "$M" ] && [ -d "$R" ] || { echo "model or runtime not found (M=$M R=$R)"; exit 1; }
THREADS=$(nproc)
PROMPT='{"messages":[{"role":"user","content":"Explain in 150 words why the sky is blue."}],"max_tokens":150,"temperature":0}'
for S in none draft-mtp; do
  echo "== spec-type $S (loading, about 90 s on a slow disk)"
  LD_LIBRARY_PATH=$R "$R/llama-server" -m "$M" -t "$THREADS" -c 1024 --port $PORT --spec-type $S >"/tmp/ls-$S.log" 2>&1 &
  PID=$!
  for i in $(seq 1 60); do sleep 3; curl -s "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; done
  for run in 1 2; do
    curl -s "http://127.0.0.1:$PORT/v1/chat/completions" -H 'Content-Type: application/json' -d "$PROMPT" \
      | grep -o '"predicted_per_second":[0-9.]*' | sed "s/.*:/   run $run: /; s/$/ tok\/s/"
  done
  kill $PID 2>/dev/null; wait $PID 2>/dev/null
done
echo "Done. Send both tok/s values. Logs: /tmp/ls-none.log /tmp/ls-draft-mtp.log"
