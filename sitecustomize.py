"""Runtime safety patch.

Python imports sitecustomize automatically on startup when this file is on sys.path.
This ensures the approved unified spread engine is used even if an older runtime module
still calls bot.send_rasklad or product_runtime.bot.send_rasklad.
"""

try:
    import bot
    from spread_engine_approved import send_approved_rasklad

    bot.send_rasklad = send_approved_rasklad

    try:
        import product_runtime
        product_runtime.bot.send_rasklad = send_approved_rasklad
    except Exception:
        pass

    try:
        import product_runtime_final
        product_runtime_final.bot.send_rasklad = send_approved_rasklad
    except Exception:
        pass
except Exception:
    # Never break app startup from a patch module.
    pass
