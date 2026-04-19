"""
secrets_client.py — Key Vault secrets client for Migrate4HANA
==============================================================
Provides a consistent interface for Azure Key Vault secret operations
used across all pipeline stages.

Authentication:
    DefaultAzureCredential (Managed Identity in Azure, falls back to
    environment variables / Azure CLI locally).

Environment:
    AZURE_KEYVAULT_URI  — e.g. "https://migrate4hana-kv.vault.azure.net/"
"""

import os
import logging
import threading
from typing import Any, Dict, List, Optional

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.core.exceptions import (
    ResourceNotFoundError,
    HttpResponseError,
    ClientAuthenticationError,
    ServiceRequestError,
)

logger = logging.getLogger("secrets_client")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
_KEYVAULT_URI = os.environ.get("AZURE_KEYVAULT_URI", "")

# Thread-safe caching
_lock = threading.Lock()
_secret_client: Optional[SecretClient] = None
_secret_cache: Dict[str, str] = {}


def _get_secret_client() -> SecretClient:
    """Return a cached SecretClient, creating it on first call (thread-safe)."""
    global _secret_client
    if _secret_client is None:
        with _lock:
            if _secret_client is None:
                if not _KEYVAULT_URI:
                    raise EnvironmentError(
                        "AZURE_KEYVAULT_URI is not set. "
                        "Set it to your Key Vault URI, e.g. "
                        "https://migrate4hana-kv.vault.azure.net/"
                    )
                credential = DefaultAzureCredential()
                _secret_client = SecretClient(
                    vault_url=_KEYVAULT_URI, credential=credential
                )
                logger.info("SecretClient initialised for vault '%s'", _KEYVAULT_URI)
    return _secret_client


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def get_secret_value(secret_name: str, bypass_cache: bool = False) -> Dict[str, str]:
    """
    Retrieve a secret from Azure Key Vault.

    Args:
        secret_name:   Name of the secret in Key Vault.
        bypass_cache:  If True, fetches from Key Vault even if cached.

    Returns:
        {"SecretString": str}
    """
    with _lock:
        if not bypass_cache and secret_name in _secret_cache:
            logger.debug("get_secret_value: cache hit for '%s'", secret_name)
            return {"SecretString": _secret_cache[secret_name]}

    try:
        client = _get_secret_client()
        secret = client.get_secret(secret_name)
        value = secret.value or ""

        with _lock:
            _secret_cache[secret_name] = value

        logger.info("get_secret_value: fetched '%s' from Key Vault", secret_name)
        return {"SecretString": value}

    except ResourceNotFoundError:
        logger.error("Secret '%s' not found in Key Vault '%s'", secret_name, _KEYVAULT_URI)
        raise
    except ClientAuthenticationError:
        logger.error("Authentication failed for Key Vault '%s'", _KEYVAULT_URI)
        raise
    except HttpResponseError as exc:
        logger.error(
            "get_secret_value failed for '%s': %s", secret_name, exc.message
        )
        raise
    except ServiceRequestError as exc:
        logger.error("Network error fetching secret '%s': %s", secret_name, exc)
        raise


def set_secret(secret_name: str, value: str) -> Dict[str, Any]:
    """
    Create or update a secret in Azure Key Vault.

    Args:
        secret_name: Name of the secret.
        value:       Secret value (plain text or JSON string).

    Returns:
        Dict with secret metadata (name, id, version).
    """
    try:
        client = _get_secret_client()
        result = client.set_secret(secret_name, value)

        with _lock:
            _secret_cache[secret_name] = value

        logger.info("set_secret: stored '%s' in Key Vault", secret_name)
        return {
            "Name": result.name,
            "Id": result.id,
            "Version": result.properties.version,
        }

    except ClientAuthenticationError:
        logger.error("Authentication failed for Key Vault '%s'", _KEYVAULT_URI)
        raise
    except HttpResponseError as exc:
        logger.error("set_secret failed for '%s': %s", secret_name, exc.message)
        raise
    except ServiceRequestError as exc:
        logger.error("Network error storing secret '%s': %s", secret_name, exc)
        raise


def list_secrets() -> List[str]:
    """
    List all secret names in the Key Vault.

    Returns:
        List of secret name strings.
    """
    try:
        client = _get_secret_client()
        secret_names: List[str] = []
        for secret_properties in client.list_properties_of_secrets():
            if secret_properties.enabled:
                secret_names.append(secret_properties.name)

        logger.info("list_secrets: found %d secrets in Key Vault", len(secret_names))
        return secret_names

    except ClientAuthenticationError:
        logger.error("Authentication failed for Key Vault '%s'", _KEYVAULT_URI)
        raise
    except HttpResponseError as exc:
        logger.error("list_secrets failed: %s", exc.message)
        raise


def clear_cache(secret_name: Optional[str] = None) -> None:
    """
    Clear the in-memory secret cache.

    Args:
        secret_name: If provided, clear only that key; otherwise clear all.
    """
    with _lock:
        if secret_name:
            _secret_cache.pop(secret_name, None)
            logger.debug("clear_cache: evicted '%s'", secret_name)
        else:
            _secret_cache.clear()
            logger.debug("clear_cache: all entries evicted")
