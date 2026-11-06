import json

from cryptography.fernet import InvalidToken

from app.modules.ai_admin.service import cipher
from app.modules.connectors.models import Connector
from app.modules.connectors.providers import SourceFailure
from app.modules.connectors.schemas import Credentials
from app.modules.model_gateway.contracts import ModelFailure


def seal(value: Credentials, organization_id: str, connector_id: str) -> str:
    plain = {
        "token": value.token.get_secret_value(),
        "plugin_id": value.plugin_id,
        "plugin_secret": value.plugin_secret.get_secret_value(),
        "user_key": value.user_key,
    }
    try:
        return (
            cipher()
            .encrypt(json.dumps(["connector-v1", organization_id, connector_id, plain]).encode())
            .decode()
        )
    except ModelFailure:
        raise SourceFailure("credential_storage_unavailable") from None


def unseal(row: Connector) -> Credentials:
    try:
        purpose, org, identifier, value = json.loads(
            cipher().decrypt((row.credential or "").encode())
        )
        if (purpose, org, identifier) != ("connector-v1", row.organization_id, row.id):
            raise ValueError
        return Credentials.model_validate(value)
    except (InvalidToken, ValueError, TypeError, ModelFailure):
        raise SourceFailure("credential_unavailable") from None
