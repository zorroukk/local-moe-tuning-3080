#!/usr/bin/env python3
"""Measure decode/prompt t/s of a running llama-server through its API.

Usage: python decode-probe.py <port> <label>

Ground truth is the `timings` object llama-server returns inside every
/v1/chat/completions response (prompt_per_second, predicted_per_second) —
no stderr parsing. Production server stderr is often not capturable, and
KV-cache reuse makes the stderr prompt-eval line report ~1 token, so
print_timing parsing silently drops or corrupts reps.

Works against a --jinja server (uses /v1/chat/completions with `messages`,
never /completion with a raw prompt — a raw prompt through the chat template
emits end-of-turn at once and every rep measures a ~1-token generation).
Warmup request first (page cache + expert/spec caches), then timed reps at
temperature 0 + fixed seed; reps with predicted_n < 100 are dropped.
Run with the runtime supervisor task DISABLED and exactly one llama-server
up (bench-contention rule).
"""
import json, sys, time, urllib.request

PORT = sys.argv[1]
LABEL = sys.argv[2]
BASE = "http://127.0.0.1:%s" % PORT
REPS = 3
NTOK = 160
PROMPT = ("Explain the tradeoffs of mixture-of-experts routing in transformer "
          "language models. " * 40)


def wait_ready(timeout=300):
    # /health answers "ok" while weights are still loading (chat then 503s) —
    # readiness = a tiny chat request actually succeeding.
    body = json.dumps({"messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 1, "temperature": 0.0}).encode()
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                json.loads(r.read())
                return True
        except Exception:
            pass
        time.sleep(4)
    return False


def probe():
    body = json.dumps({
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": NTOK, "temperature": 0.0, "seed": 42,
    }).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    t = d.get("timings", {})
    u = d.get("usage", {})
    if t.get("predicted_n", 0) < 100:
        return None
    return (t.get("prompt_per_second"), t.get("predicted_per_second"),
            u.get("prompt_tokens"), u.get("completion_tokens"))


def main():
    if not wait_ready():
        print("NEVER_READY"); sys.exit(1)
    probe()  # warmup: page cache + expert/spec caches
    time.sleep(2)
    rows = [r for r in (probe() for _ in range(REPS)) if r]
    time.sleep(1)
    print("CONFIG %s  (response timings, %d/%d reps valid)" % (LABEL, len(rows), REPS))
    for pp, tg, pt, ct in rows:
        print("  in=%d out=%d  pp=%.1f t/s  tg=%.1f t/s" % (pt, ct, pp, tg))
    if rows:
        print("  AVG pp=%.1f  tg=%.1f" % (sum(r[0] for r in rows) / len(rows),
                                          sum(r[1] for r in rows) / len(rows)))
    else:
        print("  NO VALID REPS")


if __name__ == "__main__":
    main()
