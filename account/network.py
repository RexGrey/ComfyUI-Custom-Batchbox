"""
Network utilities for Account system.

Provides HTTP session factory with retry strategy.
Ported from BlenderAIStudio src/studio/account/network.py
"""

import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# Retry configuration
RETRY_TOTAL = 5
RETRY_STATUS_FORCELIST = [429, 500, 502, 503, 504]
RETRY_ALLOWED_METHODS = ["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"]
RETRY_BACKOFF_FACTOR = 0.5

RETRY_STRATEGY = Retry(
    total=RETRY_TOTAL,
    status_forcelist=RETRY_STATUS_FORCELIST,
    allowed_methods=RETRY_ALLOWED_METHODS,
    backoff_factor=RETRY_BACKOFF_FACTOR,
)

# HTTP adapter with retry
ADAPTER = HTTPAdapter(max_retries=RETRY_STRATEGY)


def get_session() -> requests.Session:
    """
    HTTP Session factory with retry support.
    """
    session = requests.Session()
    session.mount("https://", ADAPTER)
    session.mount("http://", ADAPTER)
    return session
