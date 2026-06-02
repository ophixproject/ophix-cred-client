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
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import find_dotenv, load_dotenv

from client_core.core import api_delete, api_get, api_post, api_put, build_client_headers, set_active_config
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


def env_get_generic(key):
    # type: (str) -> Optional[str]
    """Get env var using generic key mapping. Falls back to raw key if not mapped."""
    return os.getenv(RESERVED_KEY_NAMES.get(key, key))




def _resolve_server_config(
    server_url=None,           # type: Optional[str]
    api_token=None,            # type: Optional[str]
    ca_cert=None,              # type: Optional[str]
    exit_on_error=True,        # type: bool
    return_env_path=False,     # type: bool
    ignore_missing_keys=None,  # type: Optional[List[str]]
):
    """
    Resolve server configuration from arguments, .cred.env, .env, or environment.

    Resolution order:
      1. Explicit arguments
      2. .cred.env (preferred)
      3. .env (legacy fallback)
      4. Process environment
    """
    if ignore_missing_keys is None:
        ignore_missing_keys = []

    # Load env files (non-destructive, deterministic)
    env_path_found = None
    cred_env_path = find_dotenv(filename=ENV_FILE_NAME, usecwd=True)
    if cred_env_path:
        load_dotenv(cred_env_path)
        env_path_found = cred_env_path
    else:
        legacy_env_path = find_dotenv(usecwd=True)
        if legacy_env_path:
            load_dotenv(legacy_env_path)
            print(f"WARNING: using legacy .env — rename to {ENV_FILE_NAME} to silence this warning")
            env_path_found = legacy_env_path

    # Resolve values (new keys first, then legacy)
    server_url = (
        server_url
        or env_get_generic("SERVER")
        or env_get_generic("CREDSERVER")  # legacy
    )
    api_token = api_token or env_get_generic("API_TOKEN")
    ca_cert = ca_cert or env_get_generic("CA_CERT")

    # Validate
    errors = []

    if (not server_url) and (RESERVED_KEY_NAMES["SERVER"] not in ignore_missing_keys):
        errors.append(f"Server URL not set ({RESERVED_KEY_NAMES['SERVER']})")

    if (not api_token or len(api_token) != 64) and (RESERVED_KEY_NAMES["API_TOKEN"] not in ignore_missing_keys):
        errors.append(
            f"API token missing or invalid ({RESERVED_KEY_NAMES['API_TOKEN']} — must be 64 hex chars)"
        )

    if ca_cert:
        ca_path = Path(ca_cert)
        if not ca_path.exists():
            errors.append(f"CA cert file not found at {ca_cert}")
        else:
            ca_cert = str(ca_path.resolve())

    if errors:
        msg = "\n".join(errors)
        if exit_on_error:
            print(f"Error resolving server config:\n{msg}")
            sys.exit(1)
        else:
            raise ValueError(msg)

    if return_env_path:
        return server_url, api_token, ca_cert, env_path_found

    return server_url, api_token, ca_cert


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
    server_url, api_token, ca_cert = _resolve_server_config(server_url, api_token, ca_cert)

    if not server_url or not api_token:
        raise ValueError(
            f"Missing required configuration. Please set: {format_required_keys('SERVER', 'API_TOKEN')}"
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
    server_url, api_token, ca_cert = _resolve_server_config(server_url, api_token, ca_cert)

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
    server_url, api_token, ca_cert = _resolve_server_config(server_url, api_token, ca_cert)
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
    server_url, api_token, ca_cert = _resolve_server_config(server_url, api_token, ca_cert)
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
    _resolve_server_config()  # triggers .cred.env load

    cred_name = os.getenv(env_var_name)
    if not cred_name:
        print(f"Environment variable {env_var_name} not set. Aborting.")
        sys.exit(1)

    try:
        return fetch_credential(cred_name)["secret_json"]
    except Exception as e:
        print(f"Failed to fetch credential '{cred_name}' from credential server: {e}")
        sys.exit(1)
