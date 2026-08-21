"""
ea_client.py
------------
Thin client for the EA client API, following the same credential resolution
as upstream's ``engine.env_config`` / ``engine.ea_reconciler``: the key is
read from the environment or the gitignored project ``.env``
(``EA_API_KEY`` or ``MY_EA_API_KEY``) at call time and passed straight to
the request. It is never logged, printed, or returned by any function here.

Session 1 (API discovery) uses this to catalogue what ``dataset_mappings``
actually returns before anything is built against it.
"""

from __future__ import annotations

import os

import requests

DEFAULT_BASE_URL = "https://api.energyaspects.com/data"


def _resolve_api_key() -> str:
    key = os.environ.get("EA_API_KEY") or os.environ.get("MY_EA_API_KEY")
    if not key:
        raise RuntimeError(
            "EA API key not set. Set EA_API_KEY or MY_EA_API_KEY in the "
            "environment or project .env."
        )
    return key


def get_dataset_mappings(base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> list | dict:
    """Fetch ``/dataset_mappings`` and return the parsed JSON body.

    Raises ``requests.HTTPError`` on a non-2xx response and ``RuntimeError``
    if no API key is available. Callers are responsible for not logging or
    persisting the raw response if it turns out to carry anything sensitive.
    """
    api_key = _resolve_api_key()
    url = f"{base_url}/dataset_mappings"
    response = requests.get(
        url,
        params={"api_key": api_key},
        headers={"accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
