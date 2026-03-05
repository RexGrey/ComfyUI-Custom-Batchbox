"""
Account System for ComfyUI-Custom-Batchbox

Ported from BlenderAIStudio's Account module.
Provides user authentication, credit management, and task status tracking
for the acggit.com API proxy service.
"""

from .core import Account, AUTH_MODE_API, AUTH_MODE_ACCOUNT
from .task_history import (
    TaskStatus,
    TaskStatusData,
    TaskHistoryData,
    AccountTaskHistory,
)
from .task_sync import (
    StatusResponseParser,
    TaskSyncService,
    TaskStatusPoller,
)
from .websocket_server import WebSocketLoginServer
from .network import get_session
from .exceptions import (
    StudioException,
    NotLoggedInException,
    AuthFailedException,
    TokenExpiredException,
    InsufficientBalanceException,
    RedeemCodeException,
    APIRequestException,
)

__all__ = [
    "Account",
    "AUTH_MODE_API",
    "AUTH_MODE_ACCOUNT",
    "TaskStatus",
    "TaskStatusData",
    "TaskHistoryData",
    "AccountTaskHistory",
    "StatusResponseParser",
    "TaskSyncService",
    "TaskStatusPoller",
    "WebSocketLoginServer",
    "get_session",
    "StudioException",
    "NotLoggedInException",
    "AuthFailedException",
    "TokenExpiredException",
    "InsufficientBalanceException",
    "RedeemCodeException",
    "APIRequestException",
]
