# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Meta-internal credential access for IXIA clients."""

import typing as t

from taac.utils.oss_taac_lib_utils import await_sync


IXIA_API_PASSWORD_SECRET_NAME = "IXOSADMIN"
IXIA_API_KEY_SECRET_GROUP = "DNE_TESTING"


def fetch_ixia_password_internal(
    secret_name: t.Optional[str] = None,
    secret_group: t.Optional[str] = None,
) -> str:
    """Fetch IXIA credentials from Meta's keychain for internal runtimes."""
    actual_secret_name = secret_name or IXIA_API_PASSWORD_SECRET_NAME
    actual_secret_group = secret_group or IXIA_API_KEY_SECRET_GROUP

    try:
        from libfb.py.secrets.secrets_client_factory import SecretsClientFactory

        client = SecretsClientFactory.get_client(
            caller_id="neteng.test_infra.dne.taac.ixia.internal_credentials"
        )
        secret = await_sync(
            client.gen_secret_from_group(actual_secret_name, actual_secret_group)
        )
        password = secret.get_value_as_str()
    except Exception as error:
        raise Exception(
            "Cannot retrieve password from keychain secret name: "
            f"{actual_secret_name} group: {actual_secret_group}. "
            f"Error: {error}"
        ) from error

    if password is None:
        raise Exception(
            "Cannot retrieve password from keychain secret name: "
            f"{actual_secret_name} group: {actual_secret_group}"
        )
    return password
