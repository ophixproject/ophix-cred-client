"""
cred_client.cli
~~~~~~~~~~~~~~~
Command-line interface for the Ophix credential client.

Entry point: cred-client (registered in pyproject.toml).
"""

import json
import sys
from typing import List, Tuple

import requests
from dotenv import dotenv_values, set_key

from client_core.commands import build_commands
from client_core.core import resolve_server_config
from client_core.parser import make_main

from cred_client._config import CLIENT_CONFIG
from cred_client.core import (
    ENV_FILE_NAME,
    RESERVED_KEY_NAMES,
    create_credential,
    fetch_credential,
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
# Domain command handlers
# ---------------------------------------------------------------------------

EXCLUDED_ENV_KEYS = set(RESERVED_KEY_NAMES.values())


def cmd_fetch(args):
    # type: (object) -> None
    name = args.name
    if args.var:
        _, _, _, dotenv_path = resolve_server_config(CLIENT_CONFIG, return_env_path=True)
        name = dotenv_values(dotenv_path).get(args.var)
        if not name:
            print("Error: {} is not set in {}".format(args.var, ENV_FILE_NAME))
            sys.exit(1)
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


def _check_one(cred_name):
    # type: (str) -> Tuple[bool, str]
    try:
        fetch_credential(cred_name)
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


def cmd_check(args):
    # type: (object) -> None
    if args.all:
        _, _, _, dotenv_path = resolve_server_config(CLIENT_CONFIG, return_env_path=True)
        env_vars = dotenv_values(dotenv_path)
        keys = sorted(k for k in env_vars if k not in EXCLUDED_ENV_KEYS)
        if not keys:
            print("No credential variables found in {}".format(ENV_FILE_NAME))
            sys.exit(1)
        header = ["ENV KEY", "CRED NAME", "RESULT"]
        if args.verbose:
            header.append("DETAIL")
        rows = [header]
        for key in keys:
            cred_name = env_vars.get(key)
            ok, msg = _check_one(cred_name)
            row = [key, cred_name, "OK" if ok else "ERROR"]
            if args.verbose:
                row.append("" if ok else msg)
            rows.append(row)
        print(format_table(rows))
    elif args.var:
        _, _, _, dotenv_path = resolve_server_config(CLIENT_CONFIG, return_env_path=True)
        env_vars = dotenv_values(dotenv_path)
        if args.var not in env_vars:
            print("Key {} not found in {}".format(args.var, dotenv_path))
            sys.exit(1)
        ok, msg = _check_one(env_vars[args.var])
        print("OK" if ok else (msg if args.verbose else "ERROR"))
        if not ok:
            sys.exit(1)
    else:
        ok, msg = _check_one(args.name)
        print("OK" if ok else (msg if args.verbose else "ERROR"))
        if not ok:
            sys.exit(1)


def cmd_import(args):
    # type: (object) -> None
    base_url, token, ca_cert, dotenv_path = resolve_server_config(CLIENT_CONFIG, return_env_path=True)
    name = args.name
    if args.name and args.var:
        env_vars = dotenv_values(dotenv_path)
        existing = env_vars.get(args.var)
        if existing is not None and existing != args.name:
            print(
                "Error: {} is already mapped to '{}' in {}. "
                "Use --name {} to match, or edit {} manually.".format(
                    args.var, existing, ENV_FILE_NAME, existing, ENV_FILE_NAME
                )
            )
            sys.exit(1)
        if existing is None:
            set_key(dotenv_path, args.var, args.name)
            print("Mapped {}={} in {}".format(args.var, args.name, ENV_FILE_NAME))
    elif args.var:
        env_vars = dotenv_values(dotenv_path)
        name = env_vars.get(args.var)

    if not name:
        print("Credential name not specified")
        sys.exit(1)

    if not args.input_file:
        print("--input-file is required")
        sys.exit(1)

    try:
        with open(args.input_file, "r") as f:
            secret_json = json.load(f)
    except Exception as e:
        print("Failed to read input file: {}".format(e))
        sys.exit(1)

    try:
        if args.overwrite:
            result = update_credential(
                name, secret_json, description=args.description,
                server_url=base_url, api_token=token, ca_cert=ca_cert,
            )
            print("Credential '{}' updated successfully".format(result.get("name", name)))
        else:
            result = create_credential(
                name, secret_json, description=args.description,
                server_url=base_url, api_token=token, ca_cert=ca_cert,
            )
            print("Credential '{}' created successfully".format(result.get("name", name)))
    except requests.HTTPError as e:
        if e.response is not None:
            print(e.response.text)
        else:
            print(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

COMMANDS = build_commands(CLIENT_CONFIG)

COMMANDS["fetch"] = {
    "help": "Fetch a named credential from the server",
    "mutually_exclusive_groups": [
        {
            "required": True,
            "arguments": [
                {"name": "--name", "metavar": "NAME", "help": "Credential name"},
                {"name": "--var", "metavar": "ENV_VAR",
                 "help": "Env var in .cred.env holding the credential name"},
            ],
        }
    ],
    "arguments": [],
    "handler": cmd_fetch,
}

COMMANDS["import"] = {
    "help": "Import or update a credential on the server",
    "arguments": [
        {"name": "--name", "metavar": "NAME", "help": "Credential name"},
        {"name": "--var", "metavar": "ENV_VAR",
         "help": "Env var in .cred.env holding the credential name"},
        {"name": "--input-file", "required": True, "help": "JSON file containing secret"},
        {"name": "--description", "help": "Credential description"},
        {"name": "--overwrite", "action": "store_true", "help": "Update existing credential"},
    ],
    "handler": cmd_import,
}

COMMANDS["check"] = {
    "help": "Verify credential retrieval",
    "mutually_exclusive_groups": [
        {
            "required": True,
            "arguments": [
                {"name": "--all", "action": "store_true"},
                {"name": "--var", "metavar": "ENV_VAR"},
                {"name": "--name", "metavar": "NAME"},
            ],
        }
    ],
    "arguments": [
        {"name": "--verbose", "action": "store_true", "help": "Show detailed error messages"},
    ],
    "handler": cmd_check,
}


main = make_main(CLIENT_CONFIG, COMMANDS)


if __name__ == "__main__":
    main()
