# Cache/checkpoint reuse probe for llama-server — measures whether turn-2 re-prefills.
# Usage: python ckpt-reuse-probe.py <port> [label] [model-alias]
# Probe llama-server DIRECTLY (the turbofit gateway strips prompt_eval_count from timings).
# Verdict: new_tokens_processed ~0 on T2 = reuse works; ~= in tokens = full re-prefill
# (hybrid checkpoint bugs). For spec-decode rounds, run once with and once without the
# spec flags — draft-mtp on hybrids can silently destroy prompt-cache reuse.
import json, sys, time, urllib.request

PORT = sys.argv[1]; LABEL = sys.argv[2] if len(sys.argv) > 2 else "srv"
MODEL = sys.argv[3] if len(sys.argv) > 3 else "ornith-35b-a3b"
BASE = "http://127.0.0.1:%s" % PORT

def wait_ready(timeout=420):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=5) as r:
                if json.loads(r.read()).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(4)
    return False

def chat(messages, max_tokens=60):
    body = json.dumps({"model": MODEL, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.6}).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1200) as r:
        d = json.loads(r.read())
    wall = time.time() - t0
    t = d.get("timings", {}); u = d.get("usage", {})
    tg = t.get("predicted_per_second") or 0
    out = t.get("predicted_n") or u.get("completion_tokens") or 0
    newtok = max(0, round(wall - out / tg)) * (t.get("prompt_per_second") or 0) if tg else -1
    return "in=%d out=%d wall=%.1fs tg=%.1f new_tokens_processed~%d" % (
        u.get("prompt_tokens", 0), out, wall, tg, newtok)

filler = ("The lighthouse keeper logged every ship that passed the strait: its name, tonnage, "
          "heading and the weather at the time. These entries, written in a careful hand across "
          "forty winters, became the archive that later historians would argue over. ")
big = "ARCHIVE-SEED-7734. Summarize the following log excerpt in one short sentence. " + filler * 60

if not wait_ready():
    print("REUSE %s NEVER_READY" % LABEL); sys.exit(1)
chat([{"role": "user", "content": "warmup"}], max_tokens=8)
msgs = [{"role": "user", "content": big}]
print("REUSE %s T1: %s" % (LABEL, chat(msgs)))
msgs2 = msgs + [{"role": "assistant", "content": "Noted."},
                {"role": "user", "content": "What tonnage rule is mentioned? Answer briefly."}]
print("REUSE %s T2: %s" % (LABEL, chat(msgs2)))
