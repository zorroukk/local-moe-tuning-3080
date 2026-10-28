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

| File | Source (repo @ revision) | Size (bytes) | SHA-256 | Card license |
|---|---|---:|---|---|
| `Ornith-1.5-35B-A3B-APEX-MTP-I-Compact.gguf` | `mudler/Ornith-1.5-35B-A3B-APEX-MTP-GGUF` @ `4c326713` | 17,437,861,408 | `67e6cdff678e67180d3cd4eef55277277563319057de287b8855c4d1fbff4165` | Apache-2.0 |
| `mtp-Ornith-1.5-35B-A3B-Q8_0.gguf` | `AtomicChat/Ornith-1.5-35B-A3B-GGUF` @ `bd4dd275` | 1,990,649,856 | `c3191614e6863b908349fe5c29cd15a24c181bdab98b16089f7271a806ab79af` | MIT |

Verify with `sha256sum` after download — matching size alone does not prove correct contents or a consistent revision across range-requests.

## What each non-obvious flag does here

- `--n-cpu-moe 30` — routed experts live in system RAM. The publisher formula
  `n-cpu-moe = 40 − floor((VRAM_GB − 4.3)/0.49)` gives **29** on a 10 GB card; production runs
  **30** (one extra expert block on GPU — an empirical choice that measured fine). Never 41:
  block 40 is the MTP head, and 41 would put the drafter on CPU.
- `--model-draft … -ngld 99 --spec-type draft-mtp --spec-draft-n-max 1` — external Q8_0 MTP
  draft head (+10% decode, 81.6% acceptance). n-max 1 is the measured winner; n3 neutral, n6 −26%.
- `--load-mode mlock` — pins the model in RAM; observed mitigation for Windows working-set
  trimming, which collapsed decode to 4–8 t/s on this rig (no controlled pressure test yet).
  Costs pinned RAM.
- `--fit on` — VRAM fitter; with `--flash-attn on` and 64k f16 KV it fills the card (~5 GB KV;
  check the startup allocation log after any ctx/KV change).

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
