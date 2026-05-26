# ophix-cred-client

Python client for [ophix-creds](https://github.com/ophixproject/ophix-creds) credential servers.

Provides a CLI for operators and an importable library for automation scripts
and Tier 2 clients. Credentials are fetched on demand and never persisted to disk.

---

## Installation

```bash
pip install ophix-cred-client venv-cmds
```

`venv-cmds` is optional but recommended — it provides `venv-cmds list` to discover all
commands available in the venv and `venv-cmds check_updates` to check for new releases.

---

## Quick start

```bash
# Bootstrap in one step
cred-client quickstart https://credserver.internal my-client

# Fetch a credential (JSON printed to stdout)
cred-client fetch my-database-password

# Check all credentials mapped in .cred.env
cred-client check --all

# Diagnose config and connectivity
cred-client doctor
```

---

## Configuration

Settings are stored in `.cred.env` (mode 600).

| Variable | Purpose |
| --- | --- |
| `CREDSERVER_URL` | Base URL of the credential server |
| `CREDSERVER_API_TOKEN` | 64-char hex API token (set by `register`) |
| `CREDSERVER_CA_CERT` | Path to CA certificate (set by `download ca-cert`) |

Additional keys in `.cred.env` are treated as credential name mappings used by
`check --all` — each key maps an environment variable name to a credential name
on the server.

---

## CLI reference

```text
cred-client quickstart <server_url> <client_name> [--deployment-ref ...]
cred-client fetch {--name <n>|--var <VAR>}
cred-client register <name> [deployment_ref]
cred-client update [--deployment-ref ...]
cred-client set {server|ca-cert|token} <value>
cred-client download ca-cert
cred-client import --input-file <file> [--name <n>] [--var <VAR>] [--description ...] [--overwrite]
cred-client check {--all|--var <VAR>|--name <name>} [--verbose]
cred-client info
cred-client rotate-token
cred-client doctor
```

### fetch

| Usage | What happens |
| --- | --- |
| `--name <n>` | Fetches the credential named `<n>` directly |
| `--var <VAR>` | Reads the credential name from `<VAR>` in `.cred.env`, then fetches it |

### import

Uploads a JSON file as a credential on the server. The credential name is resolved from the flags provided:

| Flags | Behaviour |
| --- | --- |
| `--name <n>` only | Creates the credential with the given name |
| `--var <VAR>` only | Reads the credential name from the `<VAR>` mapping already in `.cred.env` |
| `--name <n> --var <VAR>` | Writes `<VAR>=<n>` to `.cred.env`, then creates the credential — one step setup for Tier 2 consumers |

When `--name` and `--var` are both given and `<VAR>` already exists in `.cred.env` with a **different** name, the command refuses with an error. If it already maps to the same name, it proceeds normally.

Add `--overwrite` to update an existing credential instead of creating a new one (requires `can_update` on the server-side link).

---

## Python API — Tier 2 clients

```python
from cred_client.core import get_cred

# Reads credential name from the named env var, fetches from server,
# returns the secret as a dict. Calls sys.exit(1) on failure.
db_creds = get_cred("DB_CRED_NAME")
password = db_creds["password"]
```

Full CRUD:

```python
from cred_client.core import (
    fetch_credential,   # returns secret dict
    create_credential,
    update_credential,
    delete_credential,
)
```

---

## Server

This client connects to [ophix-creds](https://github.com/ophixproject/ophix-creds).
