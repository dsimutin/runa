"""Shared HTML building blocks for user-facing rune readings."""

from html import escape


def reading_title(icon: str, title: str) -> str:
    """Return the common first line used by every automated reading."""
    return f"{icon} <b>{escape(title)}</b>"


def rune_block(name: str, orientation: str | None = None) -> str:
    """Make a rune name visually scannable, with an optional position label."""
    result = f"ᚱ <b>{escape(str(name))}</b>"
    if orientation:
        result += f"\n<i>{escape(str(orientation))}</i>"
    return result


def section_title(icon: str, title: str) -> str:
    """Return a consistent heading for a semantic block inside a reading."""
    return f"{icon} <b>{escape(title)}</b>"
