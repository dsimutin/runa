# PATCHED MAIN BLOCK ONLY
import os

FORCE_WEBHOOK = bool(os.getenv("RENDER_EXTERNAL_URL"))

if FORCE_WEBHOOK:
    WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL").rstrip("/")


def main() -> None:
    app = build_application()

    if FORCE_WEBHOOK:
        print("FORCED WEBHOOK MODE (Render)")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", "10000")),
            url_path="webhook",
            webhook_url=f"{WEBHOOK_URL}/webhook",
            drop_pending_updates=True,
        )
        return

    # LOCAL ONLY
    print("LOCAL POLLING MODE")
    app.run_polling()


if __name__ == "__main__":
    main()
