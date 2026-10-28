# Task-spectrum workload battery for a llama-server (arg: port, default 8092).
# Run in a DEDICATED cycle (supervisor task disabled, bench server, agent idle)
# — the parallel-1 server contends with the agent's own inference and reads
# 7-12 t/s garbage otherwise. Prints per-task in/out/pp/tg/wall + validity
# flags; rag_8k_warm shows prefix reuse (in<500 = reuse works).
import json, sys, time, urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8092"
BASE = "http://127.0.0.1:%s/v1/chat/completions" % PORT
MODEL = "ornith-35b-a3b"  # match --alias

CODE_SRC = '''import json
from pathlib import Path

def load_config(path):
    with open(path) as f:
        raw = json.load(f)
    cfg = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        cfg[k] = v
    return cfg

def save_config(path, cfg):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    tmp.replace(path)

def merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out

def validate(cfg):
    errors = []
    if not isinstance(cfg.get("port"), int):
        errors.append("port must be an integer")
    if cfg.get("host") not in ("127.0.0.1", "0.0.0.0"):
        errors.append("host must be 127.0.0.1 or 0.0.0.0")
    if not cfg.get("model"):
        errors.append("model is required")
    return errors
'''

RAG_DOC = ("The quarterly infrastructure report covers twelve regions. " +
("Region throughput grew 4 percent quarter over quarter while latency budgets tightened by 15 percent. "
"Capacity planning assumes the current fleet of consumer GPUs remains in service through next summer, "
"with memory bandwidth identified as the dominant constraint for inference workloads. "
"Cache hit rates above 80 percent reduce effective cost per request by roughly a third. "
"The team recommends prefix caching, speculative decoding, and quantization ladders tuned per device class. ") * 45)

def chat(messages, max_tokens, temp=0.7):
    body = json.dumps({"model": MODEL, "messages": messages,
                       "max_tokens": max_tokens, "temperature": temp}).encode()
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.loads(r.read())
    wall = time.time() - t0
    t = d.get("timings", {})
    content = d["choices"][0]["message"].get("content") or ""
    return {"in": t.get("prompt_n", 0), "out": t.get("predicted_n", 0),
            "pp": t.get("prompt_per_second") or 0, "tg": t.get("predicted_per_second") or 0,
            "wall": round(wall, 1), "content": content}

def report(name, r, extra=""):
    print("TASK %-12s in=%-5s out=%-4s pp=%6.1f tg=%6.1f wall=%6.1fs %s" %
          (name, r["in"], r["out"], r["pp"], r["tg"], r["wall"], extra))

def wait_ready(timeout=300):
    # /health answers ok while the model is still loading — retry the CHAT.
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            chat([{"role": "user", "content": "Reply with exactly: READY"}], 200)
            return True
        except Exception:
            pass
        time.sleep(3)
    return False

if not wait_ready():
    print("BATTERY never_ready"); sys.exit(1)

r = chat([{"role": "user", "content": "What is the capital of Norway? One sentence."}], 150)
report("chat_short", r, "ttft~%.2fs" % (r["in"] / max(r["pp"], 1)))

r = chat([{"role": "user", "content":
    "Write a Python function `rotate_logs(log_dir, keep=5)` that finds all *.log files, sorts by mtime, "
    "and deletes all but the newest `keep`. Include a docstring, type hints, and error handling. "
    "Output only the code."}], 700)
report("code_gen", r, "has_def=%s" % ("def rotate_logs" in r["content"]))

r = chat([{"role": "user", "content":
    "Fix the bug in this module: load_config must also reject keys containing spaces. "
    "Output the complete corrected file, nothing else:\n\n" + CODE_SRC}], 1200)
report("code_edit", r, "fixed=%s" % ("space" in r["content"].lower()))

r = chat([{"role": "system", "content":
    "You are a tool-calling agent. Reply ONLY with a JSON object matching the schema "
    "{\"tool\": string, \"args\": {\"path\": string, \"pattern\": string}}."},
    {"role": "user", "content": "Find all yaml config files under /etc/app and call the tool."}], 200)
try:
    j = json.loads(r["content"]); ok = "tool" in j and "args" in j
except Exception:
    ok = False
report("json_tool", r, "valid_json=%s" % ok)

r = chat([{"role": "user", "content":
    "Write a detailed 800-word explanation of why memory bandwidth, not FLOPS, limits local LLM inference "
    "on consumer GPUs. Cover prefill vs decode, MoE routing, quantization, and speculative decoding."}], 1500)
report("long_gen", r)

msgs = [{"role": "user", "content": "Summarize the key recommendations in this report in 3 bullets:\n\n" + RAG_DOC}]
r1 = chat(msgs, 300); report("rag_8k_cold", r1)
r2 = chat(msgs + [{"role": "assistant", "content": "ok"}] +
          [{"role": "user", "content": "Now give me just the single most important one."}], 200)
report("rag_8k_warm", r2, "reuse=%s" % (r2["in"] < 500))

r = chat([{"role": "user", "content":
    "Translate the following Norwegian text to English, preserving tone and paragraph structure:\n\n"
    "Kysten nord for Bergen er et av de mest dramatiske landskapene i Norge. Om vinteren slår stormene "
    "inn over øyene, og lyset kommer lavt og kaldt over horisonten. Fiskere har i generasjoner fulgt "
    "strømmene og vindene, og landsbyene bærer preg av et liv i nært samarbeid med havet. I dag er "
    "næringen i endring, men tradisjonene lever videre i språket, maten og minnene."}], 800)
report("translate", r)

print("BATTERY_DONE")
