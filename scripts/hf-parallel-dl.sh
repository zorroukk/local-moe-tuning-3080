#!/usr/bin/env bash
# Parallel Hugging Face GGUF downloader — defeats HF single-connection throttling
# (~1 MB/s single vs ~10 MB/s with 16 connections on this rig).
# Re-entrant: run with NO args to orchestrate; run with N to fetch part N only.
# MSYS bash has no working `export -f` — the self-call-via-xargs pattern replaces it.
# TOTAL MUST be the exact byte size from the HF API tree endpoint — a TOTAL that is
# too big silently short-parts the last chunk (curl -C - then reports the part
# complete at the wrong size) and assembly aborts with ASSEMBLY_SKIPPED_PARTS_BAD.
#   size lookup: https://huggingface.co/api/models/<repo>/tree/main
# Usage: edit the four constants, then:
#   bash hf-parallel-dl.sh
URL="https://huggingface.co/<repo>/resolve/main/<file>.gguf"
OUT="C:/path/to/<file>.gguf"
PARTS="C:/path/to/parts_dir"
TOTAL=0            # exact bytes from the HF API tree listing
CHUNK=1073741824   # 1 GiB per connection

N=$(( (TOTAL + CHUNK - 1) / CHUNK ))
if [ -z "$1" ]; then
  mkdir -p "$PARTS"
  seq 0 $((N-1)) | xargs -P 16 -I{} bash "$0" {} 2>&1 | tail -2
  rc=$?
  bad=0
  for i in $(seq 0 $((N-1))); do
    want=$CHUNK; last=$((N-1))
    [ "$i" -eq "$last" ] && want=$(( TOTAL - i*CHUNK ))
    have=$(stat -c %s "$PARTS/part_$i" 2>/dev/null || echo 0)
    [ "$have" -ne "$want" ] && { echo "part_$i have=$have want=$want"; bad=1; }
  done
  echo "parallel_fetch_rc=$rc"
  if [ "$bad" -eq 0 ]; then
    rm -f "$OUT"; mkdir -p "$(dirname "$OUT")"
    for i in $(seq 0 $((N-1))); do cat "$PARTS/part_$i" >> "$OUT"; done
    fs=$(stat -c %s "$OUT")
    if [ "$fs" -eq "$TOTAL" ]; then
      rm -rf "$PARTS"; echo "FINAL_SIZE=$fs EXPECTED=$TOTAL"; echo "DOWNLOAD_OK"
    else
      rm -f "$OUT"; echo "ASSEMBLY_SIZE_BAD $fs != $TOTAL"
    fi
  else
    echo "ASSEMBLY_SKIPPED_PARTS_BAD (re-run to resume — curl -C - continues parts)"
  fi
else
  i=$1
  start=$((i*CHUNK))
  end=$(( start + CHUNK - 1 )); [ $end -ge $TOTAL ] && end=$((TOTAL-1))
  curl -sL -C - --retry 8 --retry-delay 3 --connect-timeout 15 \
    -H "Range: bytes=${start}-${end}" -o "$PARTS/part_$i" "$URL"
fi
