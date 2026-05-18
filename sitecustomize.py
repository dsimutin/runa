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

    # product_runtime_final is not imported here: it's the __main__ entry point
    # and importing it from sitecustomize would cause its module-level code to
    # run twice (once as a module, once as __main__), which is unnecessary.
except Exception:
    # Never break app startup from a patch module.
    pass
