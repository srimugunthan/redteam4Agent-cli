"""Mock Tool Server for AgentRedTeam — Phase 5B.

A lightweight FastAPI server that serves adversarial payloads for injection
attacks (A-02, B-04). Routes are configured via MockRouteConfig objects.
The server runs in a background thread to avoid event-loop conflicts in tests.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import List, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agentrt.config.settings import MockRouteConfig


class MockToolServer:
    """Lightweight FastAPI server serving adversarial payloads for injection attacks."""

    def __init__(
        self,
        routes: Optional[List[MockRouteConfig]] = None,
        port: int = 0,
    ) -> None:
        """
        routes: list of MockRouteConfig objects defining path → response mappings.
                If None or empty, server starts with no routes (404 on everything).
        port:   TCP port. 0 means pick a random available port (recommended for tests).
        """
        self._routes: List[MockRouteConfig] = list(routes) if routes else []

        # Pick an available port immediately so base_url is valid before start().
        if port == 0:
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                self._port = s.getsockname()[1]
        else:
            self._port = port

        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the server in a background thread. Returns when server is ready."""
        app = self._build_app()

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self._port,
            log_level="error",
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        # Wait until uvicorn has bound the socket and is ready to accept connections.
        while not self._server.started:
            time.sleep(0.01)

    async def stop(self) -> None:
        """Shutdown the server and join the background thread."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    @property
    def base_url(self) -> str:
        """Return 'http://127.0.0.1:<port>'. Valid immediately after __init__."""
        return f"http://127.0.0.1:{self._port}"

    def add_route(self, path: str, response: dict) -> None:
        """Dynamically add a route. Must be called before start()."""
        self._routes.append(MockRouteConfig(path=path, response=response))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_app(self) -> FastAPI:
        """Build the FastAPI application from the configured routes."""
        app = FastAPI()

        for route_cfg in self._routes:
            path = route_cfg.path
            resp = route_cfg.response

            # Use a factory to capture the loop variable correctly.
            def make_handler(r: dict):
                async def handler() -> JSONResponse:
                    return JSONResponse(r)
                return handler

            app.add_api_route(
                path,
                make_handler(resp),
                methods=["GET", "POST"],
            )

        return app
