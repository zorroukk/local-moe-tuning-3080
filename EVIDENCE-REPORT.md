# Local MoE LLM Tuning on an RTX 3080 / 32 GB Rig — Full Evidence Report

**Date:** 2026-10-27/28 (two-day benchmark program)
**Author:** zorroukk (with Hermes agent as measurement harness)
**License:** MIT (text and data; model weights belong to their publishers)
**Purpose:** complete record of actions, measurements and decisions so another AI system or human can cross-reference, challenge, or replicate the work.

---

## 1. Rig and runtime

| Item | Value |
|---|---|
| GPU | RTX 3080 10 GB (PCIe 3.0), Ampere sm_86 |
| RAM | 32 GB system RAM |
| CPU | i7-12700F |
| OS | Windows 11 |
| Runtime | llama.cpp **b11935, CUDA 12** build (dated 2026-10-27) |
| Server mode | `llama-server` with OpenAI-compatible API, one supervisor scheduled task auto-restarting it |

**Goal:** a dependable local model for agent traffic (chat, tool-calls, code, RAG-style reuse) as fallback insurance against remote API lanes. Selection criterion: agent reliability first, raw benchmark speed second.

**Model family under test:** Ornith-1.5-35B-A3B — a ~35B-total / ~3B-active MoE with hybrid GDN (gated delta-net) layers and an MTP (multi-token-prediction) tail layer, GGUF format.

---

## 2. Final configuration (the winner)

```
llama-server \
  --model   Ornith-1.5-35B-A3B-APEX-MTP-I-Compact.gguf \   # 17.44 GB
  --model-draft mtp-Ornith-1.5-35B-A3B-Q8_0.gguf \         # 1.99 GB external MTP head
  -ngld 99 \
  --spec-type draft-mtp --spec-draft-n-max 1 \
  --load-mode mlock \
  --ctx-size 65536 --parallel 1 \
  --n-gpu-layers 99 --n-cpu-moe 30 \
  --fit on --flash-attn on --jinja --metrics
```

Measured decode progression on the standard bench prompt (611-token prompt, 160-token output, temp 0, seed 42, 3 reps + warmup):

| Stage | tg (t/s) | Gain |
|---|---:|---|
| Ornith Q4_K_M, plain flags (day-1 production) | 43.8 | baseline |
| Swap to APEX-MTP-I-Compact quant | 52.5 | +20% |
| + `--load-mode mlock` | 52.5–53.9 | neutral-to-positive + reliability |
| + external Q8_0 MTP draft head, n-max 1 | **58.9–60.7** | +10% |
| **Total** | **~57 average** | **+30% over two days** |

---

## 3. Benchmark methodology (rules learned the hard way)

These rules exist because each was violated once and produced garbage data:

1. **Dedicated cycles.** The server runs `--parallel 1`; any other inference (including the supervising agent's own turns) contends with it. Bench rounds must disable the supervisor task and run alone.
2. **Baseline gate per round.** Every round starts and ends with the known-good config. If the gate doesn't reproduce within noise (~±10%), the round is contaminated and must be discarded or discounted.
3. **`/health` lies.** b11935 returns `status: ok` while the model is still loading (chat returns 503). Readiness probes must issue a real chat completion, not trust `/health`.
4. **Free-RAM check at cycle start.** A previous server's mlock'd 17 GB footprint can take seconds to release; starting a bench server against 8 GB free produces page-thrash numbers (4–16 t/s) that look like config failures.
5. **Warmup rep before measurement.** First request after load pays cold costs; discard it.
6. **Acceptance rates must be measured at production sampling on production traffic.** Speculative-decode claims from publishers (often greedy, often different hardware) do not transfer directly.
7. **Server-side timings only.** `timings.prompt_per_second` / `predicted_per_second` from the response, not wall-clock client math.

---

## 4. Model ladder — what was tried and kept

| Model (quant) | Size | tg | pp | Quality | Verdict |
|---|---:|---:|---:|---|---|
| Ornith-1.5-35B-A3B **Q4_K_M** | 21.9 GB | 43.8 | 47.2 | reference | superseded |
| **Ornith APEX-MTP-I-Compact** (mixed ladder) | 17.44 GB | 52.5 | 39–46 | ≡ Tiel (own A/B); Q4-band KLD | **kept** |
| Tiel-Coder-35B-A3B-MTP UD-IQ4_XS | 18.1 GB | 40.1 | 36.4 | quality tie with Compact | deleted (−24% speed) |
| Ornith AD-IQ3_S-IQ3_XXS | 15.5 GB | 43.9 | 38.1 | KLD 0.087 / Top-1 88% (publisher) | deleted (−17% speed) |
| Qwen3.8-27B dense (earlier era) | ~16 GB | ~4–8 | — | — | dead on this rig (dense MoE-bandwidth) |

**Byte rule (within one quant family):** tg ≈ 910 / file_GB on this rig (Q4_K_M 21.9→43.8, Compact 17.44→52.2 predicted, 52.5 measured). **The rule breaks across quant shapes:** IQ4_XS decodes ~20% worse per byte than a mixed Q4 ladder; IQ3 worse still (predicted 58.7, measured 43.9). Smaller-file speed plays are dead on mainline llama.cpp CUDA kernels; they may revive on ik_llama.cpp (see §9).

**Quality A/B (Compact vs Tiel):** head-to-head tie on agent tasks (code, tool-calls, reasoning excerpts) — decided on speed. Publisher KLD ladder (AtomicChat, vs BF16): Q4-class 0.032–0.048 / Top-1 91–94%; IQ3-class 0.087 / 88%; IQ2-class 0.14 / 84.7% — quality cliff below Q4 for tool-calling.

---

## 5. Flag sweeps — every lever measured, with verdicts

| Lever | Flags | tg | Verdict |
|---|---|---:|---|
| **mlock** | `--load-mode mlock` | 52.5–53.9 | **APPLIED.** Neutral-to-positive speed; the only known countermeasure to Windows working-set trimming (documented failure: OS trimmed 12/21.9 GB → decode 4–8 t/s). Proof of activation: zero `failed to mlock` lines AND the `mmap enabled - consider --load-mode none` warning disappears. |
| **MTP, built-in Q3_K head** | `--spec-type draft-mtp --spec-draft-n-max 3` | 35.4 (−33%) | rejected — 27–28% acceptance; verify pass re-reads expert stream per drafted token (bandwidth tax) |
| **MTP, external Q8_0 head** | `--model-draft mtp-Q8_0 -ngld 99 --spec-type draft-mtp` | **n1: 58.9 (+10%)** n3: 53.7 n6: 39.9 | **APPLIED at n-max 1.** Acceptance **81.6%** (vs 27% built-in). Reproduces publisher sweep shape (unsloth card, their box: n1 83.3%/1.22×, n3 59.9%/1.16×, n8 30.2%/0.60×). Head quality was the whole problem, not the mechanism. |
| ngram-mod | `--spec-type draft-mtp,ngram-mod` | n3: 3.2 n8: 28.4 | rejected for agent traffic — but copy probe (verbatim repeat) hit **74–132 t/s** at n8 (mean draft len 59, 91% accept): a copy-only trick |
| auto-offload | drop `--n-gpu-layers`/`--n-cpu-moe`, let `--fit` auto | 50.7 | rejected — best pp (48.6) but tg −3% and re-opens the VRAM-estimator cliff |
| no-mmap prefill | `--load-mode none -ctk q8_0 -ctv q8_0` | 52.3, pp 45.2 | rejected — loads (unlike the 18 GB model, which NEVER_READY'd) but the community-claimed 2.4× prefill win does not reproduce on b11935 |
| ub2048 | `-b 2048 -ub 2048` | 49.8 | rejected (worse) |
| KV q8_0 | `-ctk q8_0 -ctv q8_0` | 39.4 (Tiel sweep) | neutral-to-negative on decode; useful only as VRAM relief |
| moe-cache | `--moe-cache` | 23.1 / 16.6 | catastrophic, dead |
| ngl reduction | lower `--n-gpu-layers` | — | never: on this rig experts belong on CPU via ncmoe, layers on GPU |

**n-cpu-moe placement rule (publisher formula, peculiar-ragdoll):** `n-cpu-moe = 40 − floor((VRAM_GB − 4.3) / 0.49)` → **30** on a 10 GB card. Never 41: the MTP tail is block 40, and 41 puts the drafter on CPU.

---

## 6. Task-spectrum battery (production config, dedicated cycle, temp 0.7)

| Task | in→out | tg | wall | Signal |
|---|---|---:|---:|---|
| Short chat | 20→40 | 52.6 | 1.0 s | TTFT ~0.2 s |
| Code gen from spec | 62→700 | 54.6 | 13.3 s | fastest real workload |
| Code edit (rewrite file) | 332→839 | 21.9 | 40.3 s | slow; failed an added requirement 3/3 |
| JSON tool-call | 65→79 | 21.2 | 6.2 s | valid JSON 2/3 |
| Long analytical gen | 55→1500 | 28.1 | 60.1 s | thinking-heavy band |
| RAG 3.9k ctx cold | 3858→300 | 31.4 | 55.2 s | **prefill 84.7 t/s** — scales up with size |
| RAG follow-up warm | 29→200 | 32.1 | 6.8 s | ~99% prefix reuse |
| Translate NO→EN | 133→523 | 33.9 | 18.3 s | mid band |

**Surmise:** the bench-prompt tg (54–60) is a **ceiling** for structured/creative output; long analytical/thinking-heavy generations decode at 21–34. Local lane is strongest for chat, code-gen, tool loops, and anything multi-turn (reuse makes follow-ups nearly free). Long precise reasoning is better served by a strong remote model.

---

## 7. Reliability and cache findings

- **Windows page-trim thrash** is the dominant failure mode for large local models on 32 GB Windows: the OS trims the server's mmap'd working set under pressure → decode collapses to 4–8 t/s. `--load-mode mlock` pins the model and eliminates it. Cost: pinned RAM (heavy games/other-GPU-apps need the model stopped).
- **`preserve_thinking` is on by default** in b11935 for this chat template ("chat template supports preserving reasoning, it is enabled by default"). Community template analysis: preserving reasoning keeps **100% prefix KV-cache hit** across multi-turn; disabling it rewrites history and invalidates the cache. Never set `--reasoning off` (generate-then-strip creates KV/history mismatch, ik_llama.cpp #1898).
- **Prefix reuse measured:** follow-up turns process ~0 new tokens; shared prefixes re-process at ~373 t/s. Reuse survives MTP being enabled (llama.cpp #28049 — draft tokens accepted past first EOG breaking reuse — fixed upstream by PR #29638, merged 2026-09-29; b11935 carries it; confirmed locally).
- **MTP acceptance is workload- and sampler-dependent:** unsloth PR #144 measured 70.7% acceptance greedy vs 38.7–50.4% at default sampling on the same model. Our own: 27% (Q3_K head) → 81.6% (Q8_0 head) → 83–86% across the task battery. Any MTP claim must be re-measured at production sampling on production traffic.
- **VRAM budget on 10 GB:** model GPU slice + 64k f16 KV (~5 GB) + 2 GB Q8_0 draft head ≈ full card. No room for `--parallel 2` or vision mmproj without q8_0 KV relief.

---

## 8. Negative results (the learning payload)

1. Smaller quants (IQ4_XS, IQ3) decode **slower per byte** on mainline CUDA kernels — the byte rule only holds within one quant shape family.
2. Built-in low-bit MTP heads (Q3_K) have too-low acceptance to pay for verification bandwidth on a PCIe 3.0 consumer card; an external Q8_0 head flips the sign.
3. ngram-mod speculation: catastrophic on general traffic (3.2–28 t/s), excellent on verbatim copy (74–132 t/s). Workload-split speculation is real but not switchable per-request in practice.
4. `--load-mode none` (no-mmap) prefill win (community-claimed 2.4×) does not reproduce on b11935 — cross-rig, cross-era claims need local replication.
5. moe-cache: catastrophic (−57% to −69%).
6. Dense 27B models are dead on this rig class (bandwidth-bound decode reads all 27B active weights per token); MoE 3B-active is the right shape for 10 GB + 32 GB.
7. `/health` readiness, parallel-1 self-contention, and mlock'd RAM release lag each produced at least one contaminated measurement before harness rules were written.

---

## 9. Open frontiers (not yet done)

- **ik_llama.cpp as second runtime:** fused MoE/delta-net kernels, MTP acceptance bug #1814 fixed (PRs #1815/#1816, May 2026), qwen35moe MTP tail support, 142–146 t/s reported on an RTX 3090 (bandwidth ~1.6× ours). No Windows prebuilt CUDA binaries exist (upstream releases are 2025-era); needs CUDA toolkit + VS Build Tools + 1–2 h build. KT quants (IQ4_KT) would additionally need the BF16 base (~70 GB) and a quantize run.
- **Vision:** mmproj F16 (~1 GB) available for the model family; blocked by VRAM ceiling without q8_0 KV.
- **Per-workload speculation:** ngram for copy lanes, MTP for the rest — possible with routing, untested.

---

## 10. Citations and credits

- **unsloth** — Ornith-1.5-35B-A3B and Tiel-Coder-35B-A3B-MTP model cards (MTP n-max sweep data, quantization guidance); unsloth PR #144 (acceptance sampler-dependence).
- **mudler** — `Ornith-1.5-35B-A3B-APEX-MTP-GGUF` (the APEX-MTP-I-Compact mixed-ladder quant that won).
- **AtomicChat** — `Ornith-1.5-35B-A3B-GGUF` AD-ladder quants, KLD/Top-1 quality table, and the standalone `mtp-...-Q8_0.gguf` draft head that produced the +10%.
- **peculiar-ragdoll** — UD quant ladders and the `n-cpu-moe` placement formula used verbatim.
- **llama.cpp maintainers** — b11935; issue #28049 / PR #29638 (speculative-decode reuse fix); `preserve_thinking` default.
- **ik_llama.cpp (ikawrakow)** — issue #1814 / PRs #1815 #1816 (MTP acceptance fix), #1976 (checkpoint), #1898 (reasoning-preserve mismatch); phase-2 runtime candidate.
- **spiritbuun llama.cpp fork** — checkpoint-bug workarounds (#22384/#24055); evaluated, unnecessary on b11935.
- **Community reports** (no canonical URL, treated as claims until locally replicated): davetha's no-mmap prefill notes (did NOT reproduce, §5); a Strix Halo datapost on workload-split draft acceptance (code/tool ~0.96 vs reasoning ~0.5 at n-max 12); a Qwen forum recipe for auto-offload flags (did not reproduce, §5).

All numbers in this report are server-side `timings` values from llama.cpp b11935 on the rig in §1, reproducible with the scripts in this repo.
