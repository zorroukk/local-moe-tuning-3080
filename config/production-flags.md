# Production configuration (final, 2026-10-28)

The winning `llama-server` invocation on the RTX 3080 10 GB / 32 GB rig (llama.cpp b11935, CUDA 12):

```
llama-server \
  --model   Ornith-1.5-35B-A3B-APEX-MTP-I-Compact.gguf \
  --model-draft mtp-Ornith-1.5-35B-A3B-Q8_0.gguf \
  -ngld 99 \
  --spec-type draft-mtp --spec-draft-n-max 1 \
  --load-mode mlock \
  --host 127.0.0.1 --port 8092 --alias ornith-35b-a3b \
  --ctx-size 65536 --parallel 1 \
  --n-gpu-layers 99 --n-cpu-moe 30 \
  --fit on --flash-attn on --jinja --metrics
```

Model files (Hugging Face):

| File | Source | Size |
|---|---|---:|
| `Ornith-1.5-35B-A3B-APEX-MTP-I-Compact.gguf` | `mudler/Ornith-1.5-35B-A3B-APEX-MTP-GGUF` | 17.44 GB |
| `mtp-Ornith-1.5-35B-A3B-Q8_0.gguf` | `AtomicChat/Ornith-1.5-35B-A3B-GGUF` | 1.99 GB |

## What each non-obvious flag does here

- `--n-cpu-moe 30` — routed experts live in system RAM; 30 comes from the publisher formula
  `n-cpu-moe = 40 − floor((VRAM_GB − 4.3)/0.49)` for a 10 GB card. Never 41: block 40 is the
  MTP head, and 41 would put the drafter on CPU.
- `--model-draft … -ngld 99 --spec-type draft-mtp --spec-draft-n-max 1` — external Q8_0 MTP
  draft head (+10% decode, 81.6% acceptance). n-max 1 is the measured winner; n3 neutral, n6 −26%.
- `--load-mode mlock` — pins the model in RAM; the only countermeasure found for Windows
  working-set trimming, which otherwise collapses decode to 4–8 t/s. Costs pinned RAM.
- `--fit on` — VRAM fitter; with `--flash-attn on` and 64k f16 KV the card is exactly full.

## Running it supervised (Windows Task Scheduler)

The server is kept alive by a scheduled task (`TurbofitRuntime`) that relaunches it with the
arguments above. To change any flag: export the task XML (`schtasks /query /tn TurbofitRuntime /xml`),
patch `<Arguments>`, re-register with `schtasks /create /f /tn TurbofitRuntime /xml <file>`,
then `/end` + kill the server + `/run`. Verify the flag landed:

```powershell
(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'").CommandLine
```

The same procedure is the rollback. On Linux, the equivalent is a systemd unit.

## Rollback

Rolling back the model swap = swapping the `--model` path back to
`Ornith-1.5-35B-A3B-Q4_K_M.gguf` (21.9 GB, tg 43.8) and dropping the draft-head flags.
Rolling back MTP = removing `--model-draft`, `-ngld`, `--spec-type`, `--spec-draft-n-max`.
