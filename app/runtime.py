"""Explicit Windows-compatible async runtime; production Linux keeps its standard loop."""

import asyncio
import sys


def loop_factory():
    return asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()


def run(coroutine):
    return asyncio.run(coroutine, loop_factory=loop_factory)
