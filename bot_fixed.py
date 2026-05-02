import runpy

# Stable launcher. The current production bot code remains in bot.py.
# Use this file as Render Start Command if bot.py updates are blocked.

if __name__ == "__main__":
    runpy.run_path("bot.py", run_name="__main__")
