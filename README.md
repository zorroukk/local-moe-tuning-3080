# Local MoE LLM tuning on an RTX 3080 — a two-day benchmark program, in full

Everything measured while picking and tuning a local 35B-class MoE (Ornith-1.5-35B-A3B, GGUF)
to run agent traffic on a **consumer rig: RTX 3080 10 GB (PCIe 3.0), 32 GB RAM, i7-12700F,
Windows 11, llama.cpp b11935 CUDA 12** — including every lever that *failed*, with the raw logs.

**Result: 43.8 → 58.9 t/s decode (+34.5%) and a final flag set where every candidate was
measured neutral-or-negative.** The negative results are the payload: most community speed
claims did not reproduce on this rig class.

## Headline numbers

| Stage | tg (t/s) | Gain |
|---|---:|---|
| Ornith Q4_K_M, plain flags | 43.8 | baseline |
| Swap to APEX-MTP-I-Compact quant (17.44 GB) | 52.5 | +20% |
| `--load-mode mlock` | 52.5–53.9 | reliability (observed mitigation for Windows page-trim thrash) |
| External Q8_0 MTP draft head, n-max 1 | **58.9** (60.7 was a 60-token reuse-probe peak, not the standard bench) | +10% |

Rejected after measurement: built-in MTP head (−33%; head precision vs head revision are
confounded in that comparison — see EVIDENCE-REPORT §5), ngram-mod (−38% on agent traffic but
Round L's gates were contaminated, so treat it as an observation needing a clean re-run;
+73% on verbatim copy only), `--moe-cache` (−46%/−62% vs gate 43.1), no-mmap prefill
(community 2.4× claim did not reproduce in our short repeated-prompt test), ub2048, q8_0 KV,
auto-offload, IQ3/IQ4_XS quants (slower per byte).

## Start here

1. **[EVIDENCE-REPORT.md](EVIDENCE-REPORT.md)** — the full record: rig, methodology, every
   round with numbers, reliability findings, negative results, open frontiers, citations.
2. **[config/production-flags.md](config/production-flags.md)** — the winning `llama-server`
   invocation, what each non-obvious flag does, how to change/roll back safely.
3. **[LEARNINGS.md](LEARNINGS.md)** — the decision tables: which lever to try in which order,
   the tg prediction rule (`tg ≈ 910 / file_GB` within a quant family), the `n-cpu-moe`
   placement formula, how to check whether a GGUF carries an MTP head.
4. **[results/](results/)** — raw bench logs (paths genericized), one file per round.
5. **[scripts/](scripts/)** — the measurement harness:
   - `decode-probe.py` — tg/pp from server-side `timings` (temp 0, seed 42, 3 reps)
   - `ckpt-reuse-probe.py` — does prompt-cache reuse survive (spec decode / checkpoints)?
   - `copy-probe.py` — verbatim-copy workload probe (exposes copy-only spec wins)
   - `task-battery.py` — task-spectrum battery (chat/code/tool/RAG/translate) with warmup
   - `cycle_bench_template.ps1` — the supervisor-off → gated cycles → restore pattern
   - `hf-parallel-dl.sh` — parallel-range Hugging Face downloader (~10× single-connection)

## Replicating

```bash
# 1. download the two GGUFs (see config/production-flags.md for exact repos + SHA-256)
bash scripts/hf-parallel-dl.sh            # EDIT the URL/OUT/TOTAL vars at the top first
                                          # (or any downloader; files are 17.44 + 1.99 GB)

# 2. launch with the production flags (config/production-flags.md)

# 3. measure
python scripts/decode-probe.py 8092 mylabel
python scripts/ckpt-reuse-probe.py 8092 mylabel
python scripts/task-battery.py 8092
```

Bench rules that keep the numbers honest (each was learned by getting it wrong once):
dedicated cycles with the supervisor off, baseline gate at round start AND end, free-RAM
check before each cycle, warmup rep discarded, judge spec-decode on tg **and** turn-2 reuse,
and never trust `/health` for readiness (chat-probe instead). Details in EVIDENCE-REPORT §3.

## Credits and citations

Base model: **ornith-ai (Ornith Team)** — [ornith-ai/Ornith-1.5-35B-A3B](https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B) (MIT). Full bibliography with links in [EVIDENCE-REPORT.md §10](EVIDENCE-REPORT.md): unsloth (quantization/tooling), mudler (the winning APEX quant, Apache-2.0 card), AtomicChat (AD quants + the Q8_0 draft head, MIT), peculiar-ragdoll (UD ladders, the ncmoe formula and the MTP n-max sweep table, MIT), llama.cpp and ik_llama.cpp maintainers (issues/PRs that shaped the findings), plus community reports we tested (flagged as unverified claims).

Upstream weights keep their publishers' licenses (base model MIT, APEX card Apache-2.0); this repo bundles no weights — its text, data and scripts are MIT.

## License

MIT — see [LICENSE](LICENSE).
