"""Render entry point — delegates to product_runtime_final (full product stack).

product_runtime_final.py:
- sets the 6-button keyboard (Руна дня / Вопрос / Расклад / Личный расклад /
  Настройки / Помощь) via product_runtime.py
- runs 5-question onboarding
- uses rune_text_repository for card-of-day, spread and sphere texts
"""

import runpy

runpy.run_module("product_runtime_final", run_name="__main__")
