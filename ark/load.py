"""Load the exported Ark Parquet files into a running Helix Foundry, headlessly.

This runs the same sequence the guided setup does (AI, then Data, then
Ontology) through the app's own API, so the person giving the demo opens the
browser onto a built workspace instead of a setup wizard. It talks to the app on
loopback without an Authorization header, which the app treats as the local
owner; that is why the container runs in the app's network namespace.

Usage: python load.py DATA_DIR
Environment:
  FOUNDRY_URL           default http://127.0.0.1:3001
  ANTHROPIC_API_KEY     when set, setup uses Claude; otherwise the local model
  ARK_DEMO_CLAUDE_MODEL default claude-sonnet-5-5
  ARK_DEMO_LOCAL_MODEL  default qwen3:4b
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("FOUNDRY_URL", "http://127.0.0.1:3001").rstrip("/") + "/api/v1"


def call(method, path, body=None, headers=None, data=None, timeout=60):
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:500]}")


def upload(w, path):
    """Multipart upload of one file to the setup endpoint.

    The idempotency key is derived from the file name and size, so re-running
    the loader after a partial failure reuses the uploads that already landed.
    """
    name = os.path.basename(path)
    with open(path, "rb") as f:
        content = f.read()
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    key = f"ark-demo-{name}-{len(content)}"
    return call(
        "POST",
        f"/workspaces/{w}/onboarding/uploads",
        data=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}", "idempotency-key": key},
        timeout=600,
    )


def wait(what, check, minutes):
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        state = check()
        if state:
            return state
        time.sleep(3)
    raise SystemExit(f"Timed out waiting for {what}.")


def main(data_dir):
    me = call("GET", "/me")
    w = me["workspaces"][0]["id"]
    state = call("GET", f"/workspaces/{w}/onboarding")
    if state.get("complete"):
        print("This workspace is already set up. Reset it with ./ark/demo.sh --reset to load fresh data.")
        return

    key = os.environ.get("ANTHROPIC_API_KEY")
    provider = (
        {"provider": "claude", "model": os.environ.get("ARK_DEMO_CLAUDE_MODEL", "claude-sonnet-5-5"), "apiKey": key}
        if key
        else {"provider": "local", "model": os.environ.get("ARK_DEMO_LOCAL_MODEL", "qwen3:4b")}
    )
    print(f"AI provider: {provider['provider']} ({provider['model']})")
    call("POST", f"/workspaces/{w}/onboarding/provider", {**provider, "advanceToData": True})

    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".parquet"))
    if not files:
        raise SystemExit(f"No Parquet files in {data_dir}. Run the export first.")
    for f in files:
        upload(w, os.path.join(data_dir, f))
        print(f"  uploaded {f}")

    def imported():
        s = call("GET", f"/workspaces/{w}/onboarding")
        failed = [j["name"] for j in s.get("imports", []) if j.get("data", {}).get("status") in ("failed", "canceled")]
        if failed:
            raise SystemExit(f"Import failed for: {', '.join(failed)}. Open the app to see why.")
        return s if not s.get("blockers") else None

    wait("imports", imported, 20)
    print("Imports done. Suggesting the ontology...")

    state = call("POST", f"/workspaces/{w}/onboarding/ontology", {}, timeout=600)
    ontology = state.get("ontology") or {}
    if not ontology.get("hash"):
        raise SystemExit("The app returned no ontology suggestion; open the browser to finish setup.")
    call("POST", f"/workspaces/{w}/onboarding/ontology/confirm", {"hash": ontology["hash"]}, timeout=600)
    print("Ontology confirmed. Building the workspace...")

    def built():
        s = call("GET", f"/workspaces/{w}/onboarding")
        run = s.get("buildRun") or {}
        if (run.get("data") or {}).get("status") == "failed":
            raise SystemExit(f"Workspace build failed: {json.dumps(run.get('data'))[:500]}")
        return s if s.get("complete") else None

    wait("the workspace build", built, 15)
    print("Workspace ready.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
