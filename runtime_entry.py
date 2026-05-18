"""Compatibility shim: Render dashboard startCommand still points here.

Delegates to product_runtime_final, which is the real entry point.
"""

import runpy

runpy.run_module("product_runtime_final", run_name="__main__")
