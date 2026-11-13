#!/bin/sh
# One-shot Ollama initialization; only local container storage is modified.
set -eu

: "${OLLAMA_MODEL:?Set OLLAMA_MODEL}"
: "${MODEL_GGUF_SHA256:?Set MODEL_GGUF_SHA256}"
import_dir="${MODEL_IMPORT_DIR:-/model-import}"
state_dir="${MODEL_IMPORT_STATE_DIR:-/root/.ollama/capstone-imports}"
gguf="$import_dir/Llama-3.2-3B-Instruct.Q4_K_M.gguf"
recipe="$import_dir/Modelfile"

if [ ! -f "$gguf" ] || [ ! -f "$recipe" ]; then
    echo "Missing GGUF or import recipe; refusing to use a fallback model." >&2
    exit 1
fi
actual_sha=$(sha256sum "$gguf" | cut -d ' ' -f 1)
if [ "$actual_sha" != "$MODEL_GGUF_SHA256" ]; then
    echo "GGUF checksum mismatch; model import stopped." >&2
    exit 1
fi
recipe_sha=$(sha256sum "$recipe" | cut -d ' ' -f 1)
key=$(printf '%s' "$OLLAMA_MODEL" | sha256sum | cut -d ' ' -f 1)
mkdir -p "$state_dir"
state="$state_dir/$key"
installed=$(ollama show "$OLLAMA_MODEL" --modelfile 2>/dev/null || true)
installed_sha=$(printf '%s' "$installed" | sha256sum | cut -d ' ' -f 1)
fingerprint=$(printf '%s\n%s\n%s' "$actual_sha" "$recipe_sha" "$installed_sha")
if [ -n "$installed" ] && [ -f "$state" ] && [ "$(cat "$state")" = "$fingerprint" ]; then
    echo "Verified model already imported; retaining its persistent state."
    exit 0
fi
ollama create "$OLLAMA_MODEL" -f "$recipe"
installed=$(ollama show "$OLLAMA_MODEL" --modelfile)
if [ -z "$installed" ]; then
    echo "Imported model could not be verified." >&2
    exit 1
fi
installed_sha=$(printf '%s' "$installed" | sha256sum | cut -d ' ' -f 1)
printf '%s\n%s\n%s\n' "$actual_sha" "$recipe_sha" "$installed_sha" > "$state.tmp"
mv "$state.tmp" "$state"
echo "Verified and imported the selected GGUF into containerized Ollama."
