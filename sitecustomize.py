"""Runtime environment fixes.

Python imports this module automatically on startup when it is present on sys.path.
It makes Render deployments use webhook mode even when WEBHOOK_URL is not set manually.
"""

import os

render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
manual_url = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")

if not manual_url and render_url:
    os.environ["WEBHOOK_URL"] = render_url

if not os.getenv("WEBHOOK_PATH", "").strip():
    os.environ["WEBHOOK_PATH"] = "webhook"
