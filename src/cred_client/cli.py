"""
cred_client.cli
~~~~~~~~~~~~~~~
Command-line interface for the Ophix credential client.

Entry point: cred-client (registered in pyproject.toml).
"""

import json
import os
import re
import secrets
import sys
import urllib3
from pathlib import Path
from typing import Dict, Any, List, Mapping, Optional, Tuple

import requests
from dotenv import find_dotenv, set_key, dotenv_values

from cred_client.core import (
    ENV_FILE_NAME,
    RESERVED_KEY_NAMES,
    _resolve_server_config,
    build_client_headers,
    create_credential,
    fetch_credential,
    get_client_version,
    in_venv,
    update_credential,
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_table(rows):
    # type: (List[List[str]]) -> str
    if not rows:
        return ""
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]

    def fmt(row):
        return "  ".join(str(col).ljust(widths[i]) for i, col in enumerate(row))

    return "\n".join(fmt(row) for row in rows)


# ---------------------------------------------------------------------------
# Environment file helpers
# ---------------------------------------------------------------------------

def find_project_root():
    # type: () -> Path
    cwd = Path.cwd()

    venv_root = in_venv()
    if venv_root:
        return venv_root.parent

    for parent in [cwd] + list(cwd.parents):
        if (
            (parent / "requirements.txt").exists()
            or (parent / ".git").exists()
            or (parent / ".env").exists()
        ):
            return parent

    return cwd


def determine_repo_name():
    # type: () -> str
    venv_root = in_venv()
    if not venv_root:
        raise RuntimeError("Cannot determine parent: not running inside a virtual environment.")
    return venv_root.parent.name


def ensure_env_file():
    # type: () -> Path
    project_root = find_project_root()
    env_file = find_dotenv(filename=ENV_FILE_NAME, usecwd=True)

    if not env_file:
        env_path = project_root / ENV_FILE_NAME
        # Create securely: rw------- (600)
        fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        print("Created {} with secure permissions (600)".format(env_path))
        return env_path

    env_path = Path(env_file)

    try:
        mode = env_path.stat().st_mode & 0o777
        if mode != 0o600:
            os.chmod(str(env_path), 0o600)
            print("Secured permissions on {} (600)".format(env_path))
    except Exception:
        pass

    return env_path


def set_env_variable(var, value, verbose=True):
    # type: (str, str, bool) -> None
    env_file = ensure_env_file()
    set_key(str(env_file), var, value)
    if verbose:
        print("Set {} in {} to {}".format(var, ENV_FILE_NAME, value))


# ---------------------------------------------------------------------------
# CLI command implementations
# ---------------------------------------------------------------------------

EXCLUDED_ENV_KEYS = set(RESERVED_KEY_NAMES.values())


def fetch_credential_cli(name):
    # type: (str) -> None
    try:
        creds = fetch_credential(name)
        print(json.dumps(creds, indent=2))
    except requests.HTTPError as e:
        print("Failed to fetch credential {}: {}".format(name, e))
        if e.response is not None:
            print(e.response.text)
        sys.exit(1)
    except Exception as e:
        print("Unexpected error: {}".format(e))
        sys.exit(1)


def perform_credential_check(name):
    # type: (str) -> Tuple[bool, str]
    """Returns (success, message)."""
    try:
        fetch_credential(name)
        return True, "OK"
    except requests.HTTPError as e:
        try:
            err = e.response.json()
            msg = err.get("detail") or err.get("error") or str(err)
        except Exception:
            msg = e.response.text.strip() or str(e)
        return False, msg
    except Exception as e:
        return False, str(e)


def run_check_all(verbose):
    # type: (bool) -> None
    server_url, api_token, ca_cert, dotenv_path = _resolve_server_config(return_env_path=True)
    env_vars = dotenv_values(dotenv_path)

    keys = sorted(k for k in env_vars if k not in EXCLUDED_ENV_KEYS)

    if not keys:
        print("No credential variables found in {}".format(ENV_FILE_NAME))
        sys.exit(1)

    if verbose:
        rows = [["ENV KEY", "CRED NAME", "RESULT", "DETAIL"]]
    else:
        rows = [["ENV KEY", "CRED NAME", "RESULT"]]

    for key in keys:
        cred_name = env_vars.get(key)
        success, msg = perform_credential_check(cred_name)
        if verbose:
            rows.append([key, cred_name, "OK" if success else "ERROR", "" if success else msg])
        else:
            rows.append([key, cred_name, "OK" if success else "ERROR"])

    print(format_table(rows))


def run_check_var(var_name, verbose):
    # type: (str, bool) -> None
    server_url, api_token, ca_cert, dotenv_path = _resolve_server_config(return_env_path=True)
    env_vars = dotenv_values(dotenv_path)

    if var_name not in env_vars:
        print("Key {} not found in {}".format(var_name, dotenv_path))
        sys.exit(1)

    cred_name = env_vars[var_name]
    success, msg = perform_credential_check(cred_name)

    if success:
        print("OK")
    else:
        print(msg if verbose else "ERROR")
        sys.exit(1)


def run_check_name(cred_name, verbose):
    # type: (str, bool) -> None
    success, msg = perform_credential_check(cred_name)

    if success:
        print("OK")
    else:
        print(msg if verbose else "ERROR")
        sys.exit(1)


def register_client(name, deployment_ref=None):
    # type: (str, Optional[str]) -> None
    """Register a new client with the server."""
    base_url, token, ca_cert, dotenv_path = _resolve_server_config(
        return_env_path=True,
        ignore_missing_keys=[RESERVED_KEY_NAMES["API_TOKEN"]],
    )

    if base_url is None:
        print("Warning: {} not defined in {}. You can set it with:".format(
            RESERVED_KEY_NAMES["SERVER"], ENV_FILE_NAME
        ))
        print("  cred-client set server <server-url>")
        sys.exit(1)

    if token and len(token) == 64:
        print("Error: {} already present in {}. Registration should only happen once.".format(
            RESERVED_KEY_NAMES["API_TOKEN"], ENV_FILE_NAME
        ))
        sys.exit(1)

    venv_path = in_venv()
    if not venv_path:
        print("Error: Cannot detect virtual environment.")
        sys.exit(1)

    if not deployment_ref:
        deployment_ref = determine_repo_name()

    payload = {
        "name": name,
        "deployment_ref": deployment_ref,
        "venv_name": venv_path.name,
        "venv_path": str(venv_path.resolve()),
    }

    headers = build_client_headers()

    try:
        resp = requests.post(
            "{}/api/register/".format(base_url.rstrip("/")),
            json=payload,
            headers=headers,
            verify=ca_cert if ca_cert else True,
        )
        resp.raise_for_status()
    except requests.HTTPError:
        try:
            err_json = resp.json()
            server_msg = err_json.get("detail") or err_json.get("error") or str(err_json)
        except Exception:
            server_msg = resp.text.strip() or "No server message"
        print("\nFAILED TO REGISTER CLIENT")
        print("HTTP Status: {}".format(resp.status_code))
        print("Server Response: {}".format(server_msg))
        sys.exit(1)
    except requests.RequestException as e:
        print("\nFAILED TO REGISTER CLIENT - NETWORK OR CONNECTION ERROR")
        print("Error: {}".format(e))
        sys.exit(1)

    data = resp.json()
    print("Client registered successfully!")
    print("Host: {}".format(data["host"]))
    print("Name: {}".format(data["name"]))
    print("Deployment ref: {}".format(data["deployment_ref"]))
    print("API Token: {}".format(data["api_token"]))
    print("Virtual environment: {} ({})".format(venv_path.name, venv_path))

    set_env_variable(RESERVED_KEY_NAMES["API_TOKEN"], data["api_token"], verbose=False)
    print("Token saved to {}".format(dotenv_path))


def update_client(deployment_ref=None):
    # type: (Optional[str]) -> None
    """Update client info on server (venv_name/path, optionally deployment_ref)."""
    base_url, api_token, ca_cert = _resolve_server_config()

    if not base_url or not api_token or len(api_token) != 64:
        print("Error: {} and valid {} must be set in {}".format(
            RESERVED_KEY_NAMES["SERVER"], RESERVED_KEY_NAMES["API_TOKEN"], ENV_FILE_NAME
        ))
        sys.exit(1)

    venv_path = in_venv()
    if not venv_path:
        print("Error: Cannot detect virtual environment.")
        sys.exit(1)

    payload = {
        "venv_name": venv_path.name,
        "venv_path": str(venv_path.resolve()),
    }
    if deployment_ref:
        payload["deployment_ref"] = deployment_ref

    headers = build_client_headers(api_token=api_token)
    url = "{}/api/client/self/update/".format(base_url.rstrip("/"))

    try:
        resp = requests.patch(url, headers=headers, json=payload, verify=ca_cert if ca_cert else True)
        resp.raise_for_status()
    except requests.HTTPError:
        try:
            err_json = resp.json()
            server_msg = err_json.get("detail") or err_json.get("error") or str(err_json)
        except Exception:
            server_msg = resp.text.strip() or "No server message"
        print("\nFailed to update client. Server returned: {}".format(server_msg))
        sys.exit(1)
    except requests.RequestException as e:
        print("\nFailed to update client (network error): {}".format(e))
        sys.exit(1)

    print("Client updated successfully!")
    print("Virtual environment: {} ({})".format(venv_path.name, venv_path))
    if deployment_ref:
        print("Deployment ref updated to: {}".format(deployment_ref))
    else:
        print("Deployment ref not changed.")


def download_resource(args):
    # type: (Any) -> None
    base_url, token, current_ca_cert = _resolve_server_config(
        ignore_missing_keys=[RESERVED_KEY_NAMES["SERVER"], RESERVED_KEY_NAMES["API_TOKEN"]]
    )

    if not base_url:
        print("Error: {} not set in {}. Please set it first.".format(
            RESERVED_KEY_NAMES["SERVER"], ENV_FILE_NAME
        ))
        sys.exit(1)

    if current_ca_cert and Path(current_ca_cert).exists():
        print("Warning: {} already points to an existing file ({}).".format(
            RESERVED_KEY_NAMES["CA_CERT"], current_ca_cert
        ))
        print("Remove or update that entry in {} first.".format(ENV_FILE_NAME))
        sys.exit(1)

    url = "{}/api/server/ca-cert/".format(base_url.rstrip("/"))

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    headers = build_client_headers()

    try:
        resp = requests.get(url, headers=headers, verify=False)
        resp.raise_for_status()
    except requests.RequestException as e:
        print("Failed to download CA certificate from {}: {}".format(url, e))
        sys.exit(1)

    filename = "ca-cert.pem"
    cd = resp.headers.get("Content-Disposition")
    if cd:
        m = re.search(r'filename="?([^"]+)"?', cd)
        if m:
            filename = m.group(1)

    project_root = find_project_root()
    cert_dir = project_root / ".cred"
    cert_dir.mkdir(exist_ok=True)
    cert_path = cert_dir / filename

    with open(str(cert_path), "wb") as f:
        f.write(resp.content)

    set_env_variable(RESERVED_KEY_NAMES["CA_CERT"], str(cert_path), verbose=False)
    print("CA certificate saved to: {}".format(cert_path))
    print("{} updated with {}={}".format(ENV_FILE_NAME, RESERVED_KEY_NAMES["CA_CERT"], cert_path))


def rotate_api_token(args=None):
    # type: (Any) -> None
    """Rotate the client API token. New token is generated automatically."""
    base_url, old_token, ca_cert, dotenv_path = _resolve_server_config(
        return_env_path=True,
        ignore_missing_keys=[RESERVED_KEY_NAMES["SERVER"], RESERVED_KEY_NAMES["API_TOKEN"]],
    )

    if not base_url or not old_token or len(old_token) != 64:
        print("Error: {} and valid {} must be set in {}".format(
            RESERVED_KEY_NAMES["SERVER"], RESERVED_KEY_NAMES["API_TOKEN"], ENV_FILE_NAME
        ))
        sys.exit(1)

    new_token = secrets.token_hex(32)

    headers = build_client_headers(api_token=old_token)
    url = "{}/api/client/self/rotate-token/".format(base_url.rstrip("/"))

    try:
        resp = requests.post(
            url, headers=headers, json={"new_token": new_token},
            verify=ca_cert if ca_cert else True,
        )
        resp.raise_for_status()
    except requests.HTTPError:
        try:
            err_json = resp.json()
            server_msg = err_json.get("detail") or err_json.get("error") or str(err_json)
        except Exception:
            server_msg = resp.text.strip() or "No server message"
        print("\nFailed to rotate API token. Server returned: {}".format(server_msg))
        sys.exit(1)
    except requests.RequestException as e:
        print("\nFailed to rotate API token (network error): {}".format(e))
        sys.exit(1)

    set_env_variable(RESERVED_KEY_NAMES["API_TOKEN"], new_token, verbose=False)
    print("API token rotated successfully. {} updated.".format(dotenv_path))


def show_client_info(args=None):
    # type: (Any) -> None
    """Fetch and display client metadata from the server."""
    base_url, api_token, ca_cert = _resolve_server_config(
        ignore_missing_keys=[RESERVED_KEY_NAMES["SERVER"], RESERVED_KEY_NAMES["API_TOKEN"]]
    )

    if not base_url or not api_token:
        print("Error: {} and {} must be set in {}".format(
            RESERVED_KEY_NAMES["SERVER"], RESERVED_KEY_NAMES["API_TOKEN"], ENV_FILE_NAME
        ))
        sys.exit(1)

    headers = build_client_headers(api_token=api_token)

    try:
        resp = requests.get(
            "{}/api/client/self/".format(base_url.rstrip("/")),
            headers=headers,
            verify=ca_cert or True,
        )
        resp.raise_for_status()
    except requests.HTTPError as e:
        print("Failed to fetch client info: {}".format(e))
        sys.exit(1)
    except requests.RequestException as e:
        print("Network error: {}".format(e))
        sys.exit(1)

    data = resp.json()
    print("Client Name:         {}".format(data["name"]))
    print("Version:             {}".format(get_client_version()))
    print("Venv:                {}".format(data["venv_path"]))
    print("Ref:                 {}".format(data["deployment_ref"]))
    print("Last token rotation: {}".format(data["last_token_rotation"]))


def run_doctor(args=None):
    # type: (Any) -> None
    """Lightweight connectivity and auth check."""
    print("cred-client doctor\n")

    base_url, api_token, ca_cert, dotenv_path = _resolve_server_config(
        return_env_path=True,
        ignore_missing_keys=[RESERVED_KEY_NAMES["SERVER"], RESERVED_KEY_NAMES["API_TOKEN"]],
    )

    if dotenv_path:
        print("  ENV file: {}".format(dotenv_path))
    else:
        print("  No ENV file found — expected {}".format(ENV_FILE_NAME))
        return

    # Permissions check
    try:
        mode = Path(dotenv_path).stat().st_mode & 0o777
        if mode == 0o600:
            print("  ENV permissions: OK (600)")
        else:
            print("  ENV permissions: {} (recommended: 600)".format(oct(mode)))
    except Exception as e:
        print("  ENV permissions: could not check ({})".format(e))

    if base_url:
        print("  {}: {}".format(RESERVED_KEY_NAMES["SERVER"], base_url))
    else:
        print("  {}: not set".format(RESERVED_KEY_NAMES["SERVER"]))
        return

    if api_token and len(api_token) == 64:
        print("  {}: present (64 chars)".format(RESERVED_KEY_NAMES["API_TOKEN"]))
    else:
        print("  {}: missing or invalid".format(RESERVED_KEY_NAMES["API_TOKEN"]))
        return

    if ca_cert:
        if Path(ca_cert).exists():
            print("  {}: {}".format(RESERVED_KEY_NAMES["CA_CERT"], ca_cert))
        else:
            print("  {}: set but file missing: {}".format(RESERVED_KEY_NAMES["CA_CERT"], ca_cert))
            return
    else:
        print("  {}: not set (using system trust store)".format(RESERVED_KEY_NAMES["CA_CERT"]))

    print("  Version: {}".format(get_client_version()))
    print("  Python:  {}".format(sys.version.split()[0]))

    venv_path = in_venv()
    if venv_path:
        print("  Venv: {} ({})".format(venv_path.name, venv_path))
    else:
        print("  Venv: not detected")

    print("\nChecking server connectivity...")

    headers = build_client_headers(api_token=api_token)
    url = "{}/api/client/self/".format(base_url.rstrip("/"))

    try:
        resp = requests.get(url, headers=headers, verify=ca_cert or True, timeout=5)
        resp.raise_for_status()
    except requests.exceptions.SSLError as e:
        print("  TLS error: {}".format(e))
        return
    except requests.exceptions.ConnectionError as e:
        print("  Cannot connect to server: {}".format(e))
        return
    except requests.HTTPError as e:
        print("  Server returned error: {}".format(e.response.status_code))
        try:
            print(e.response.json())
        except Exception:
            print(e.response.text)
        return

    data = resp.json()
    print("  Authenticated successfully")
    print("\nClient identity:")
    print("  Name:               {}".format(data.get("name")))
    print("  Deployment ref:     {}".format(data.get("deployment_ref")))
    print("  Venv name:          {}".format(data.get("venv_name")))
    print("  Venv path:          {}".format(data.get("venv_path")))
    print("  Last token rotation:{}".format(data.get("last_token_rotation")))
    print("\nDoctor checks completed successfully")


def run_quickstart(args):
    # type: (Any) -> None
    """Bootstrap a new client: set server, install CA cert, register."""
    print("cred-client quickstart\n")

    print("Setting server URL...")
    set_env_variable(RESERVED_KEY_NAMES["SERVER"], args.server_url)

    print("Installing CA certificate...")
    download_resource(args)

    print("Registering client...")
    register_client(name=args.client_name, deployment_ref=args.deployment_ref)

    print("\nQuickstart completed successfully")


def import_credential(name, input_file, env_key, description, overwrite):
    # type: (Optional[str], Optional[str], Optional[str], Optional[str], bool) -> None
    base_url, token, ca_cert, dotenv_path = _resolve_server_config(return_env_path=True)

    if env_key:
        env_vars = dotenv_values(dotenv_path)
        name = env_vars.get(env_key)

    if not name:
        print("Credential name not specified")
        sys.exit(1)

    if not input_file:
        print("--input-file is required")
        sys.exit(1)

    try:
        with open(input_file, "r") as f:
            secret_json = json.load(f)
    except Exception as e:
        print("Failed to read input file: {}".format(e))
        sys.exit(1)

    try:
        if overwrite:
            result = update_credential(name, secret_json, description=description,
                                       server_url=base_url, api_token=token, ca_cert=ca_cert)
            print("Credential '{}' updated successfully".format(result.get("name", name)))
        else:
            result = create_credential(name, secret_json, description=description,
                                       server_url=base_url, api_token=token, ca_cert=ca_cert)
            print("Credential '{}' created successfully".format(result.get("name", name)))
    except requests.HTTPError as e:
        if e.response is not None:
            print(e.response.text)
        else:
            print(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser(prog, version, commands, description=None):
    # type: (str, str, Mapping[str, dict], Optional[str]) -> Any
    import argparse

    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("-v", "--version", action="version", version=version)

    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, spec in commands.items():
        help_text = None if spec.get("hidden") else spec.get("help")
        sub = subparsers.add_parser(
            name,
            help=help_text if help_text is not None else argparse.SUPPRESS,
        )

        for arg in spec.get("arguments", []):
            arg = arg.copy()
            arg_name = arg.pop("name")
            sub.add_argument(arg_name, **arg)

        for group_spec in spec.get("mutually_exclusive_groups", []):
            group = sub.add_mutually_exclusive_group(required=group_spec.get("required", False))
            for arg in group_spec["arguments"]:
                arg = arg.copy()
                arg_name = arg.pop("name")
                group.add_argument(arg_name, **arg)

        sub.set_defaults(func=spec["handler"])

    return parser


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

COMMANDS = {
    "quickstart": {
        "help": "Bootstrap a new client (set server, install CA cert, register)",
        "arguments": [
            {"name": "server_url",    "help": "Credential server base URL"},
            {"name": "client_name",   "help": "Client name to register"},
            {"name": "--deployment-ref", "dest": "deployment_ref",
             "help": "Optional deployment reference", "required": False},
        ],
        "handler": run_quickstart,
    },

    "fetch": {
        "help": "Fetch a named credential from the server",
        "arguments": [
            {"name": "name", "help": "Name of the credential"},
        ],
        "handler": lambda args: fetch_credential_cli(args.name),
    },

    "register": {
        "help": "Register a new client with the server",
        "arguments": [
            {"name": "name", "help": "Client name"},
            {"name": "deployment_ref", "nargs": "?",
             "help": "Deployment reference (defaults to parent directory)"},
        ],
        "handler": lambda args: register_client(args.name, args.deployment_ref),
    },

    "update": {
        "help": "Update client info (venv_name/path, optionally deployment_ref) on the server",
        "arguments": [
            {"name": "--deployment-ref", "dest": "deployment_ref",
             "help": "New deployment reference (omit to leave unchanged)"},
        ],
        "handler": lambda args: update_client(args.deployment_ref),
    },

    "set": {
        "help": "Set a configuration value in {}".format(ENV_FILE_NAME),
        "arguments": [
            {"name": "variable", "choices": ["server", "ca-cert", "token"],
             "help": "Which value to set"},
            {"name": "value", "help": "Value to store"},
        ],
        "handler": lambda args: set_env_variable(
            {"server": RESERVED_KEY_NAMES["SERVER"],
             "ca-cert": RESERVED_KEY_NAMES["CA_CERT"],
             "token": RESERVED_KEY_NAMES["API_TOKEN"]}[args.variable],
            args.value,
        ),
    },

    "import": {
        "help": "Import or update a credential on the server",
        "arguments": [
            {"name": "--name",         "help": "Credential name"},
            {"name": "--env",          "dest": "env_key", "help": "ENV var holding credential name"},
            {"name": "--input-file",   "required": True, "help": "JSON file containing secret"},
            {"name": "--description",  "help": "Credential description"},
            {"name": "--overwrite",    "action": "store_true", "help": "Update existing credential"},
        ],
        "handler": lambda args: import_credential(
            name=args.name,
            input_file=args.input_file,
            env_key=args.env_key,
            description=args.description,
            overwrite=args.overwrite,
        ),
    },

    "download": {
        "help": "Download the server CA certificate",
        "arguments": [
            {"name": "resource", "choices": ["ca-cert"],
             "help": "Resource to download"},
        ],
        "handler": download_resource,
    },

    "check": {
        "help": "Verify credential retrieval",
        "mutually_exclusive_groups": [
            {
                "required": True,
                "arguments": [
                    {"name": "--all",  "action": "store_true"},
                    {"name": "--var",  "metavar": "ENV_VAR"},
                    {"name": "--name", "metavar": "CRED_NAME"},
                ],
            }
        ],
        "arguments": [
            {"name": "--verbose", "action": "store_true", "help": "Show detailed error messages"},
        ],
        "handler": lambda args: (
            run_check_all(args.verbose) if args.all
            else run_check_var(args.var, args.verbose) if args.var
            else run_check_name(args.name, args.verbose)
        ),
    },

    "info": {
        "help": "Show client metadata from the server",
        "arguments": [],
        "handler": show_client_info,
    },

    "rotate-token": {
        "help": "Rotate API token (new token generated automatically)",
        "arguments": [],
        "handler": rotate_api_token,
    },

    "doctor": {
        "help": "Diagnose local configuration and server connectivity",
        "arguments": [],
        "handler": run_doctor,
    },
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser(
        prog="cred-client",
        version=get_client_version(),
        description="Credential client for Ophix credential server",
        commands=COMMANDS,
    )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
