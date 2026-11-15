"""
Start the NetScope API server.

This is a thin wrapper around uvicorn that selects a stable event loop on
Windows (see ``server_loop.py``); on other platforms it behaves like a normal
uvicorn run::

    python run.py                 # http://127.0.0.1:8000/
    python run.py --port 9000     # different port

The static dashboard is served from the same origin, so open the URL above
rather than using a separate Live Server.
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the NetScope API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    arguments = parser.parse_args()

    import uvicorn

    config = uvicorn.Config(
        "api.main:app",
        host=arguments.host,
        port=arguments.port,
        log_level=arguments.log_level,
        loop="server_loop:selector_loop_factory",
    )

    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
