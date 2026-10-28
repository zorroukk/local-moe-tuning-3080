import json, sys, time, urllib.request

PORT = sys.argv[1]
BASE = "http://127.0.0.1:%s/v1/chat/completions" % PORT

PASSAGE = ("The northern lights appeared for the first time over Bergen since records began. "
"Witnesses described slow green curtains folding over each other above the fjord, while the town "
"fell silent below them. Researchers from the university had been tracking the solar storm for "
"three days, measuring the particle flux hour by hour, and they had predicted the aurora would "
"reach this latitude around midnight. The prediction proved correct. By one in the morning the "
"display had intensified from a faint glow into a full corona of arcs and pillars, visible even "
"through the light pollution of the city center. Photographers lined the hillsides, tripods "
"bumping against each other in the dark, while long exposures captured colors the naked eye "
"could barely register. The geomagnetic storm index reached its highest value in over a decade, "
"and power engineers across the country watched their transformers carefully, knowing that the "
"same particles painting the sky could induce currents strong enough to burn out grid equipment. "
"By dawn the storm was already fading, and the town returned to its ordinary rhythm, though "
"phone footage of the night would circulate for weeks afterward.")

def wait_ready(timeout=420):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%s/health" % PORT, timeout=5) as r:
                if json.loads(r.read()).get("status") == "ok":
                    req = urllib.request.Request(BASE, data=json.dumps({
                        "model": "ornith-35b-a3b",
                        "messages": [{"role": "user", "content": "Reply with exactly: READY"}],
                        "max_tokens": 200}).encode(),
                        headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=300).read()
                    return True
        except Exception:
            pass
        time.sleep(4)
    return False

def chat(messages, max_tokens):
    body = json.dumps({"model": "ornith-35b-a3b", "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.0}).encode()
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1200) as r:
        return json.loads(r.read())

if not wait_ready():
    print("COPY never_ready"); sys.exit(1)

for rep in range(2):
    d = chat([{"role": "user", "content": "Repeat the following passage verbatim, with no commentary:\n\n" + PASSAGE}], 400)
    t = d.get("timings", {})
    print("COPY rep%d in=%s out=%s tg=%.1f" % (
        rep, t.get("prompt_n"), t.get("predicted_n"), t.get("predicted_per_second") or 0))
