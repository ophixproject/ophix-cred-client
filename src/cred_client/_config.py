from client_core.config import ClientConfig
from cred_client._version import __version__

CLIENT_CONFIG = ClientConfig(
    prog="cred-client",
    description="Credential client for Ophix credential server",
    env_file=".cred.env",
    server_url_key="CREDSERVER_URL",
    api_token_key="CREDSERVER_API_TOKEN",
    ca_cert_key="CREDSERVER_CA_CERT",
    client_name="cred",
    version=__version__,
)
