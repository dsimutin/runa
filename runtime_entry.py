"""Render entry point for the data-only rune bot.

The service must use bot.py directly so rune readings come only from the
uploaded data files through rune_text_repository.py.
"""

from bot import main


if __name__ == "__main__":
    main()
