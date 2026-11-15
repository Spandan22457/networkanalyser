"""
Event-loop factory used by ``run.py``.

Uvicorn 0.54 hard-codes ``ProactorEventLoop`` on Windows.  When a browser
aborts a connection while the server is accepting it, the Proactor loop can
lose its listening socket permanently::

    OSError: [WinError 64] The specified network name is no longer available
    Accept failed on a socket

The process keeps running but every later request fails until it is restarted.
``SelectorEventLoop`` handles an aborted accept without dropping the listener,
so uvicorn is pointed at :func:`selector_loop_factory` explicitly.
"""

from __future__ import annotations

import asyncio
import sys


def selector_loop_factory(use_subprocess: bool = False):
    """Create the event loop uvicorn should run on."""

    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()

    return asyncio.new_event_loop()
