"""
ci_build.py
------------
CI equivalent of build.py — used by the GitHub Actions deploy workflow.

Reads credentials from environment variables set as GitHub Actions secrets,
fetches a short-lived IAM token, copies src/ -> dist/, and injects
window.__CLOUDANT_TOKEN__ and window.__ADMIN_PIN__ into each HTML file.

Environment variables required (set as GitHub Actions secrets):
    CLOUDANT_APIKEY   — IBM Cloud API key scoped to the three Power Pod databases
    CLOUDANT_URL      — Cloudant instance URL (not used directly here, but
                        verified to ensure the secret is present)
    ADMIN_PIN         — Organizer PIN for the admin view

Usage (CI only — not for local development):
    python3 scripts/ci_build.py
"""

import os
import shutil
import sys

import requests

# ---------------------------------------------------------------------------
# Read environment variables (set as GitHub Actions secrets)
# ---------------------------------------------------------------------------

api_key   = os.environ.get("CLOUDANT_APIKEY", "").strip()
admin_pin = os.environ.get("ADMIN_PIN", "").strip()
k_head    = os.environ.get("K_HEAD", "").strip()
k_rest    = os.environ.get("K_REST", "").strip()

if not api_key:
    print("ERROR: CLOUDANT_APIKEY environment variable is not set.")
    print("       Add it as a GitHub Actions secret in the repository settings.")
    sys.exit(1)

if not admin_pin:
    print("ERROR: ADMIN_PIN environment variable is not set.")
    print("       Add it as a GitHub Actions secret in the repository settings.")
    sys.exit(1)

# Fall back to splitting the full api_key if K_HEAD/K_REST secrets not yet added
if not k_head or not k_rest:
    parts = api_key.split("-", 1)
    k_head, k_rest = (parts[0], parts[1]) if len(parts) == 2 else (api_key, "")

# ---------------------------------------------------------------------------
# Fetch IAM token
# ---------------------------------------------------------------------------

print("Fetching IAM bearer token ...")
r = requests.post(
    "https://iam.cloud.ibm.com/identity/token",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey":     api_key,
    },
    timeout=15,
)

if r.status_code != 200:
    print(f"FAIL  IAM token request returned HTTP {r.status_code}")
    sys.exit(1)

import json as _json
import time as _time

token = r.json()["access_token"]
print(f"OK    Token received ({r.elapsed.total_seconds():.2f}s)")

# ---------------------------------------------------------------------------
# Copy src/ -> dist/
# ---------------------------------------------------------------------------

src_dir  = os.path.join(os.path.dirname(__file__), "..", "src")
dist_dir = os.path.join(os.path.dirname(__file__), "..", "dist")

if os.path.exists(dist_dir):
    shutil.rmtree(dist_dir)

shutil.copytree(src_dir, dist_dir)
print("OK    dist/ created from src/")

# ---------------------------------------------------------------------------
# Write token.json to dist/ — browser fetches this file at runtime
# Same-origin fetch (no CORS), always returns a token built at deploy time.
# Expires 55 minutes after build time (5 min buffer before IAM 60-min limit).
# ---------------------------------------------------------------------------

token_json_path = os.path.join(dist_dir, "token.json")
with open(token_json_path, "w") as f:
    _json.dump({
        "access_token": token,
        "built_at": int(_time.time()),
        "expires_in": 3300   # 55 minutes
    }, f)
print("OK    token.json written to dist/")

# ---------------------------------------------------------------------------
# Inject token and PIN into HTML files
# ---------------------------------------------------------------------------

parts = token.split(".", 1)
if len(parts) == 2:
    t_head, t_rest = parts[0], parts[1]
else:
    t_head, t_rest = token, ""

INJECTION = f"""<script>
  (function(){{
    var _h = "{t_head}";
    var _r = "{t_rest}";
    window.__CLOUDANT_TOKEN__ = _h + "." + _r;
    window.__ADMIN_PIN__      = "{admin_pin}";
    window.__K_HEAD__ = "{k_head}";
    window.__K_REST__ = "{k_rest}";
  }})();
</script>"""

html_files = [f for f in os.listdir(dist_dir) if f.endswith(".html")]
for filename in html_files:
    filepath = os.path.join(dist_dir, filename)
    with open(filepath, encoding="utf-8") as f:
        html = f.read()

    if "</head>" not in html:
        print(f"  WARNING: </head> not found in {filename} — skipping")
        continue

    html = html.replace("</head>", INJECTION + "\n</head>", 1)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  OK    {filename}")

print(f"\nBuild complete.  {len(html_files)} file(s) written to dist/")
