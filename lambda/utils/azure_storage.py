"""
azure_storage.py — Azure Blob Storage wrapper for Migrate4HANA
===============================================================
Drop-in replacement for boto3 S3 calls. Provides the same interface
so Lambda handlers require minimal changes when migrating to Azure.

Authentication:
    DefaultAzureCredential (Managed Identity in Azure, falls back to
    environment variables / Azure CLI locally).

Environment:
    AZURE_STORAGE_ACCOUNT_NAME  — e.g. "migrate4hanasa"
"""

import io
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import (
    ResourceNotFoundError,
    ResourceExistsError,
    HttpResponseError,
    ClientAuthenticationError,
    ServiceRequestError,
)

logger = logging.getLogger("azure_storage")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
_STORAGE_ACCOUNT = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "")
_ACCOUNT_URL = f"https://{_STORAGE_ACCOUNT}.blob.core.windows.net" if _STORAGE_ACCOUNT else ""

# Cached client (lazy-init)
_blob_service_client: Optional[BlobServiceClient] = None


def _get_blob_service_client() -> BlobServiceClient:
    """Return a cached BlobServiceClient, creating it on first call."""
    global _blob_service_client
    if _blob_service_client is None:
        if not _STORAGE_ACCOUNT:
            raise EnvironmentError(
                "AZURE_STORAGE_ACCOUNT_NAME is not set. "
                "Set it to your Azure Storage account name."
            )
        credential = DefaultAzureCredential()
        _blob_service_client = BlobServiceClient(
            account_url=_ACCOUNT_URL, credential=credential
        )
        logger.info("BlobServiceClient initialised for account '%s'", _STORAGE_ACCOUNT)
    return _blob_service_client


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API — mirrors boto3 S3 interface
# ═══════════════════════════════════════════════════════════════════════════════


def put_object(
    container: str,
    key: str,
    data: bytes | str,
    content_type: str = "application/json",
) -> Dict[str, Any]:
    """
    Upload data to Azure Blob Storage.

    Equivalent to:
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=ct)

    Args:
        container:    Blob container name (equivalent to S3 bucket).
        key:          Blob name / path (equivalent to S3 key).
        data:         Bytes or string payload.
        content_type: MIME type for the blob.

    Returns:
        Dict with upload metadata (etag, last_modified, etc.).
    """
    if isinstance(data, str):
        data = data.encode("utf-8")

    try:
        client = _get_blob_service_client()
        blob_client = client.get_blob_client(container=container, blob=key)
        content_settings = ContentSettings(content_type=content_type)

        result = blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=content_settings,
        )
        logger.info("put_object: %s/%s (%d bytes)", container, key, len(data))
        return {
            "ETag": result.get("etag", ""),
            "LastModified": result.get("last_modified", datetime.utcnow()),
        }

    except ClientAuthenticationError:
        logger.error("Authentication failed for storage account '%s'", _STORAGE_ACCOUNT)
        raise
    except HttpResponseError as exc:
        logger.error("put_object failed for %s/%s: %s", container, key, exc.message)
        raise
    except ServiceRequestError as exc:
        logger.error("Network error uploading %s/%s: %s", container, key, exc)
        raise


def get_object(container: str, key: str) -> Dict[str, Any]:
    """
    Download a blob from Azure Blob Storage.

    Equivalent to:
        s3.get_object(Bucket=bucket, Key=key)

    Returns:
        {"Body": BytesIO, "ContentType": str, "ContentLength": int,
         "LastModified": datetime, "ETag": str}
    """
    try:
        client = _get_blob_service_client()
        blob_client = client.get_blob_client(container=container, blob=key)
        download = blob_client.download_blob()
        blob_data = download.readall()
        properties = download.properties

        logger.info("get_object: %s/%s (%d bytes)", container, key, len(blob_data))
        return {
            "Body": io.BytesIO(blob_data),
            "ContentType": properties.content_settings.content_type or "application/octet-stream",
            "ContentLength": properties.size,
            "LastModified": properties.last_modified,
            "ETag": properties.etag,
        }

    except ResourceNotFoundError:
        logger.warning("get_object: blob not found — %s/%s", container, key)
        raise
    except ClientAuthenticationError:
        logger.error("Authentication failed for storage account '%s'", _STORAGE_ACCOUNT)
        raise
    except HttpResponseError as exc:
        logger.error("get_object failed for %s/%s: %s", container, key, exc.message)
        raise


def list_objects(
    container: str, prefix: str = "", max_results: int = 5000
) -> Dict[str, Any]:
    """
    List blobs in a container, optionally filtered by prefix.

    Equivalent to:
        s3.list_objects_v2(Bucket=bucket, Prefix=prefix)

    Returns:
        {"Contents": [{"Key": str, "Size": int, "LastModified": datetime}],
         "KeyCount": int}
    """
    try:
        client = _get_blob_service_client()
        container_client = client.get_container_client(container)

        contents: List[Dict[str, Any]] = []
        blobs = container_client.list_blobs(name_starts_with=prefix or None)
        for idx, blob in enumerate(blobs):
            if idx >= max_results:
                break
            contents.append({
                "Key": blob.name,
                "Size": blob.size,
                "LastModified": blob.last_modified,
            })

        logger.info(
            "list_objects: %s prefix='%s' → %d blobs", container, prefix, len(contents)
        )
        return {"Contents": contents, "KeyCount": len(contents)}

    except ResourceNotFoundError:
        logger.warning("list_objects: container not found — %s", container)
        return {"Contents": [], "KeyCount": 0}
    except ClientAuthenticationError:
        logger.error("Authentication failed for storage account '%s'", _STORAGE_ACCOUNT)
        raise
    except HttpResponseError as exc:
        logger.error("list_objects failed for %s: %s", container, exc.message)
        raise


def delete_object(container: str, key: str) -> None:
    """
    Delete a blob from Azure Blob Storage.

    Args:
        container: Blob container name.
        key:       Blob name / path.
    """
    try:
        client = _get_blob_service_client()
        blob_client = client.get_blob_client(container=container, blob=key)
        blob_client.delete_blob()
        logger.info("delete_object: %s/%s", container, key)

    except ResourceNotFoundError:
        logger.warning("delete_object: blob not found (already deleted?) — %s/%s", container, key)
    except ClientAuthenticationError:
        logger.error("Authentication failed for storage account '%s'", _STORAGE_ACCOUNT)
        raise
    except HttpResponseError as exc:
        logger.error("delete_object failed for %s/%s: %s", container, key, exc.message)
        raise
