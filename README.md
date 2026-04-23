# ophix-cred-client

Python client for [ophix-creds](https://github.com/ophixproject/ophix-creds) credential servers.

Provides a CLI for operators and an importable library for automation scripts
and Tier 2 clients. Credentials are fetched on demand and never persisted to disk.

---

## Installation

```bash
pip install ophix-cred-client
```

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
cred-client fetch <name>
cred-client register <name> [deployment_ref]
cred-client update [--deployment-ref ...]
cred-client set {server|ca-cert|token} <value>
cred-client download ca-cert
cred-client import --input-file <file> [--name <n>|--env <VAR>] [--description ...] [--overwrite]
cred-client check {--all|--var <VAR>|--name <name>} [--verbose]
cred-client info
cred-client rotate-token
cred-client doctor
```

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
