# ONLY CHANGE BELOW
import os

if os.getenv("RENDER_EXTERNAL_URL"):
    WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")
