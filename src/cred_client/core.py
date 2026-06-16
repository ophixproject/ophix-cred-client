"""
cred_client.core
~~~~~~~~~~~~~~~~
Core library for the Ophix credential client.

Provides functions for fetching, creating, updating, and deleting credentials
from an Ophix credential server.  Import from here in Tier 2 clients:

    from cred_client.core import get_cred, fetch_credential
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from client_core.core import api_delete, api_get, api_post, api_put, build_client_headers, resolve_server_config, set_active_config
from cred_client._config import CLIENT_CONFIG

ENV_FILE_NAME = ".cred.env"

RESERVED_KEY_NAMES = {
    "SERVER":    "CREDSERVER_URL",
    "CA_CERT":   "CREDSERVER_CA_CERT",
    "API_TOKEN": "CREDSERVER_API_TOKEN",
}


def format_required_keys(*keys):
    # type: (*str) -> str
    return ", ".join(
        f"{k} (env var: {RESERVED_KEY_NAMES.get(k, k)})"
        for k in keys
    )


def fetch_credential(
    cred_name,       # type: str
    server_url=None, # type: Optional[str]
    api_token=None,  # type: Optional[str]
    ca_cert=None,    # type: Optional[str]
):
    # type: (...) -> dict
    """
    Fetch a credential from the credential server API.

    Returns the full credential dict (including secret_json).
    Raises ValueError for empty cred_name, requests.HTTPError on failure.
    """
    if not cred_name or str(cred_name).strip() == "":
        raise ValueError("No credential name specified")

    set_active_config(CLIENT_CONFIG)
    server_url, api_token, ca_cert = resolve_server_config(
        CLIENT_CONFIG, server_url, api_token, ca_cert
    )

    url = f"{server_url.rstrip('/')}/api/credentials/{cred_name}/"
    headers = build_client_headers(CLIENT_CONFIG, api_token=api_token)

    response = api_get(url, headers=headers, verify=ca_cert or True)

    if response.status_code == 404:
        raise requests.HTTPError(f"Credential '{cred_name}' not found.", response=response)

    response.raise_for_status()
    return response.json()


def create_credential(
    name,             # type: str
    secret_json,      # type: Dict[str, Any]
    description=None, # type: Optional[str]
    server_url=None,  # type: Optional[str]
    api_token=None,   # type: Optional[str]
    ca_cert=None,     # type: Optional[str]
):
    # type: (...) -> dict
    """
    Create a new credential on the server.

    Returns the server response dict. Raises requests.HTTPError on failure.
    """
    set_active_config(CLIENT_CONFIG)
    server_url, api_token, ca_cert = resolve_server_config(
        CLIENT_CONFIG, server_url, api_token, ca_cert
    )

    url = f"{server_url.rstrip('/')}/api/credentials/{name}/"
    headers = build_client_headers(CLIENT_CONFIG, api_token=api_token)

    payload = {"secret_json": secret_json}
    if description is not None:
        payload["description"] = description

    try:
        resp = api_post(url, headers=headers, json=payload, verify=ca_cert or True)
        resp.raise_for_status()
    except requests.HTTPError as e:
        try:
            err_json = resp.json()
            server_msg = err_json.get("detail") or err_json.get("error") or str(err_json)
        except Exception:
            server_msg = resp.text.strip() or str(e)
        raise requests.HTTPError(
            f"Failed to create credential '{name}': {server_msg}",
            response=resp,
        ) from e

    return resp.json()


def update_credential(
    name,             # type: str
    secret_json,      # type: Dict[str, Any]
    description=None, # type: Optional[str]
    server_url=None,  # type: Optional[str]
    api_token=None,   # type: Optional[str]
    ca_cert=None,     # type: Optional[str]
):
    # type: (...) -> dict
    """
    Update an existing credential on the server.

    Returns the updated credential dict. Raises requests.HTTPError on failure.
    """
    set_active_config(CLIENT_CONFIG)
    server_url, api_token, ca_cert = resolve_server_config(
        CLIENT_CONFIG, server_url, api_token, ca_cert
    )
    url = f"{server_url.rstrip('/')}/api/credentials/{name}/"
    headers = build_client_headers(CLIENT_CONFIG, api_token=api_token)

    payload = {"secret_json": secret_json}
    if description:
        payload["description"] = description

    try:
        resp = api_put(url, headers=headers, json=payload, verify=ca_cert or True)
        resp.raise_for_status()
    except requests.HTTPError as e:
        try:
            err_json = resp.json()
            server_msg = err_json.get("detail") or err_json.get("error") or str(err_json)
        except Exception:
            server_msg = resp.text.strip() or str(e)
        raise requests.HTTPError(
            f"Failed to update credential '{name}': {server_msg}",
            response=resp,
        ) from e

    return resp.json()


def delete_credential(
    name,            # type: str
    server_url=None, # type: Optional[str]
    api_token=None,  # type: Optional[str]
    ca_cert=None,    # type: Optional[str]
):
    # type: (...) -> dict
    """
    Delete a credential from the server.

    Returns the server response dict. Raises requests.HTTPError on failure.
    """
    set_active_config(CLIENT_CONFIG)
    server_url, api_token, ca_cert = resolve_server_config(
        CLIENT_CONFIG, server_url, api_token, ca_cert
    )
    url = f"{server_url.rstrip('/')}/api/credentials/{name}/"
    headers = build_client_headers(CLIENT_CONFIG, api_token=api_token)

    try:
        resp = api_delete(url, headers=headers, verify=ca_cert or True)
        resp.raise_for_status()
    except requests.HTTPError as e:
        try:
            err_json = resp.json()
            server_msg = err_json.get("detail") or err_json.get("error") or str(err_json)
        except Exception:
            server_msg = resp.text.strip() or str(e)
        raise requests.HTTPError(
            f"Failed to delete credential '{name}': {server_msg}",
            response=resp,
        ) from e

    return resp.json()


def get_cred(env_var_name):
    # type: (str) -> dict
    """
    Tier 2 entry point — retrieve a credential using an environment variable.

    Looks up the credential name from the named env var, then fetches
    the secret from the server and returns secret_json.

    Example::

        from cred_client.core import get_cred
        secret = get_cred("MY_CRED_NAME")
    """
    set_active_config(CLIENT_CONFIG)
    resolve_server_config(
        CLIENT_CONFIG,
        ignore_missing_keys=[
            CLIENT_CONFIG.server_url_key,
            CLIENT_CONFIG.api_token_key,
            CLIENT_CONFIG.ca_cert_key,
        ],
    )

    cred_name = os.getenv(env_var_name)
    if not cred_name:
        print(f"Environment variable {env_var_name} not set. Aborting.")
        sys.exit(1)

    try:
        return fetch_credential(cred_name)["secret_json"]
    except Exception as e:
        print(f"Failed to fetch credential '{cred_name}' from credential server: {e}")
        sys.exit(1)
