"""
WebSocket login server for Account system.

Starts a local WebSocket server to receive login callback from browser.
Ported from BlenderAIStudio src/studio/account/websocket.py
"""

import asyncio
import json
import logging
from typing import Callable, Dict

logger = logging.getLogger("batchbox.account")

try:
    from websockets.server import serve
    from websockets.exceptions import ConnectionClosedOK, ConnectionClosed
except ImportError:
    logger.warning(
        "websockets package not installed. Account login will not work. "
        "Install with: pip install websockets"
    )
    serve = None
    ConnectionClosedOK = Exception
    ConnectionClosed = Exception


class WebSocketLoginServer:
    """WebSocket server for receiving browser login callbacks.

    Flow:
    1. User clicks "Login" in ComfyUI
    2. Browser opens acggit.com login page
    3. After login, the page sends token via WebSocket to this local server
    4. Server receives token and stores it in Account
    """

    _host = "127.0.0.1"

    def __init__(self, port: int):
        self.host = self._host
        self.port = port
        self._handlers: Dict[str, Callable] = {}
        self.stop_event = asyncio.Event()

        # Register default handlers
        self.reg_handler("_default", self._default)
        self.reg_handler("query_status", self._query_status)

    def reg_handler(self, etype: str, handler: Callable):
        self._handlers[etype] = handler

    def unreg_handler(self, etype: str):
        if etype in self._handlers:
            del self._handlers[etype]

    async def call_handler(self, websocket, message: str):
        try:
            event: dict = json.loads(message)
        except json.JSONDecodeError:
            return

        if not isinstance(event, dict):
            event = {}

        etype = event.get("type", "_default")
        handler = self._handlers.get(etype, self._default)

        try:
            await handler(self, websocket, event)
        except Exception as e:
            logger.error(f"Error in handler {handler.__name__}: {e}")

    @staticmethod
    async def _default(server, websocket, event: dict):
        try:
            logger.warning(f"Default message: {event}")
            response = {
                "type": "default",
                "data": event,
            }
            await websocket.send(json.dumps(response))
        except ConnectionClosedOK:
            pass

    @staticmethod
    async def _query_status(server, websocket, event: dict):
        try:
            logger.debug(f"Query status: {event}")
            response = {
                "type": "query_status_return",
                "data": {
                    "status": "ok",
                    "host": "Blender",
                },
            }
            await websocket.send(json.dumps(response))
        except ConnectionClosedOK:
            pass

    async def handle(self, websocket, path: str = ""):
        try:
            logger.debug(f"Client Connected: {websocket}")
            async for message in websocket:
                await self.call_handler(websocket, message)
        except ConnectionClosed as e:
            logger.debug(f"Client disconnected: code={e.code}, reason='{e.reason}'")
        except Exception as e:
            logger.error(f"Client error: {e}")

    async def main(self):
        if serve is None:
            raise RuntimeError("websockets package not installed")
        async with serve(self.handle, self.host, self.port, max_size=None):
            logger.info(f"WebSocket login server running on port {self.port}")
            await self.stop_event.wait()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main())
