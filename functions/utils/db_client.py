"""
db_client.py — Cosmos DB client for Migrate4HANA
==================================================
Provides a consistent interface for Azure Cosmos DB operations
used across all pipeline stages. The ``CosmosDBTable`` class
provides a DynamoDB-compatible Table interface (for backward compatibility).

Authentication:
    DefaultAzureCredential (Managed Identity in Azure) with fallback
    to AZURE_COSMOSDB_KEY for local development.

Environment:
    AZURE_COSMOSDB_ENDPOINT  — e.g. "https://migrate4hana.documents.azure.com:443/"
    AZURE_COSMOSDB_KEY       — (optional) master key fallback for local dev
    AZURE_COSMOSDB_DATABASE  — (optional) default "migrate4hana"
"""

import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from azure.cosmos import CosmosClient, DatabaseProxy, ContainerProxy
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("db_client")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
_ENDPOINT = os.environ.get("AZURE_COSMOSDB_ENDPOINT", "")
_KEY = os.environ.get("AZURE_COSMOSDB_KEY", "")
_DATABASE_NAME = os.environ.get("AZURE_COSMOSDB_DATABASE", "migrate4hana")

# Cached client
_cosmos_client: Optional[CosmosClient] = None
_database_proxy: Optional[DatabaseProxy] = None


def _get_cosmos_client() -> CosmosClient:
    """Return a cached CosmosClient, creating it on first call."""
    global _cosmos_client
    if _cosmos_client is None:
        if not _ENDPOINT:
            raise EnvironmentError(
                "AZURE_COSMOSDB_ENDPOINT is not set. "
                "Set it to your Cosmos DB account URI."
            )
        if _KEY:
            _cosmos_client = CosmosClient(url=_ENDPOINT, credential=_KEY)
            logger.info("CosmosClient initialised with master key for '%s'", _ENDPOINT)
        else:
            credential = DefaultAzureCredential()
            _cosmos_client = CosmosClient(url=_ENDPOINT, credential=credential)
            logger.info("CosmosClient initialised with DefaultAzureCredential for '%s'", _ENDPOINT)
    return _cosmos_client


def _get_database() -> DatabaseProxy:
    """Return a cached DatabaseProxy for the application database."""
    global _database_proxy
    if _database_proxy is None:
        client = _get_cosmos_client()
        _database_proxy = client.get_database_client(_DATABASE_NAME)
        logger.info("Database proxy acquired for '%s'", _DATABASE_NAME)
    return _database_proxy


# ═══════════════════════════════════════════════════════════════════════════════
# CosmosDBTable — Cosmos DB Table interface
# ═══════════════════════════════════════════════════════════════════════════════


class CosmosDBTable:
    """
    Mimics the DynamoDB-compatible Table interface backed by an Azure Cosmos DB
    container.

    Usage::

        table = CosmosDBTable("migration-issues")
        table.put_item({"id": "ISS-001", "severity": "HIGH", ...})
        result = table.get_item({"id": "ISS-001"})
    """

    def __init__(self, container_name: str):
        self.container_name = container_name
        self._container: Optional[ContainerProxy] = None

    @property
    def container(self) -> ContainerProxy:
        """Lazy-initialise the Cosmos DB container proxy."""
        if self._container is None:
            db = _get_database()
            self._container = db.get_container_client(self.container_name)
            logger.info(
                "Container proxy acquired: %s/%s", _DATABASE_NAME, self.container_name
            )
        return self._container

    # ── query (replaces Cosmos DB table.query) ─────────────────────────────────

    def query(
        self,
        partition_key_name: str,
        partition_key_value: Any,
        index_name: Optional[str] = None,
        filter_expression: Optional[str] = None,
        projection: Optional[List[str]] = None,
        max_items: int = 1000,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Query items by partition key value.

        Args:
            partition_key_name:  Name of the partition key field.
            partition_key_value: Value to match.
            index_name:          Ignored (Cosmos uses composite indexes).
            filter_expression:   Optional SQL WHERE clause fragment.
            projection:          List of fields to return.
            max_items:           Maximum number of items to return.

        Returns:
            {"Items": [...], "Count": int}
        """
        where_clause = f"c.{partition_key_name} = @pk_value"
        if filter_expression:
            where_clause += f" AND {filter_expression}"

        select_clause = ", ".join(f"c.{f}" for f in projection) if projection else "c"
        sql = f"SELECT {select_clause} FROM c WHERE {where_clause}"

        parameters: List[Dict[str, Any]] = [
            {"name": "@pk_value", "value": partition_key_value}
        ]

        try:
            items = list(
                self.container.query_items(
                    query=sql,
                    parameters=parameters,
                    max_item_count=max_items,
                    enable_cross_partition_query=(index_name is not None),
                )
            )
            items = [self._strip_system_properties(i) for i in items]
            logger.info(
                "query: %s WHERE %s=%s → %d items",
                self.container_name, partition_key_name, partition_key_value, len(items),
            )
            return {"Items": items, "Count": len(items)}

        except CosmosHttpResponseError as exc:
            logger.error("query failed on %s: %s", self.container_name, exc.message)
            raise

    # ── scan (replaces Cosmos DB table.scan) ───────────────────────────────────

    def scan(
        self,
        projection: Optional[List[str]] = None,
        filter_expression: Optional[str] = None,
        max_items: int = 5000,
    ) -> Dict[str, Any]:
        """
        Full container scan (cross-partition query).

        Args:
            projection:        List of fields to return.
            filter_expression: Optional SQL WHERE clause fragment.
            max_items:         Maximum items to return.

        Returns:
            {"Items": [...], "Count": int}
        """
        select_clause = ", ".join(f"c.{f}" for f in projection) if projection else "c"
        sql = f"SELECT {select_clause} FROM c"
        if filter_expression:
            sql += f" WHERE {filter_expression}"

        try:
            items = list(
                self.container.query_items(
                    query=sql,
                    enable_cross_partition_query=True,
                    max_item_count=max_items,
                )
            )
            items = [self._strip_system_properties(i) for i in items]
            logger.info("scan: %s → %d items", self.container_name, len(items))
            return {"Items": items, "Count": len(items)}

        except CosmosHttpResponseError as exc:
            logger.error("scan failed on %s: %s", self.container_name, exc.message)
            raise

    # ── put_item (replaces Cosmos DB table.put_item) ───────────────────────────

    def put_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upsert (create or replace) a document in the container.

        Legacy ``ttl`` field is mapped to Cosmos DB ``_ttl`` for native
        TTL support.

        Args:
            item: Document dict. Must include the partition key (typically "id").

        Returns:
            The upserted document dict.
        """
        doc = dict(item)
        doc = self._map_ttl_to_cosmos(doc)

        try:
            result = self.container.upsert_item(body=doc)
            logger.info("put_item: %s id=%s", self.container_name, doc.get("id", "?"))
            return self._strip_system_properties(result)

        except CosmosHttpResponseError as exc:
            logger.error("put_item failed on %s: %s", self.container_name, exc.message)
            raise

    # ── get_item (replaces Cosmos DB table.get_item) ───────────────────────────

    def get_item(self, key_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read a single document by its key.

        Args:
            key_dict: Dict with partition key (and optional sort key) values.
                      The first value is used as the Cosmos ``id`` and
                      partition key.

        Returns:
            {"Item": dict} if found, {"Item": None} if not.
        """
        item_id, partition_key = self._extract_key(key_dict)

        try:
            doc = self.container.read_item(item=item_id, partition_key=partition_key)
            logger.info("get_item: %s id=%s → found", self.container_name, item_id)
            return {"Item": self._strip_system_properties(doc)}

        except CosmosResourceNotFoundError:
            logger.info("get_item: %s id=%s → not found", self.container_name, item_id)
            return {"Item": None}
        except CosmosHttpResponseError as exc:
            logger.error("get_item failed on %s: %s", self.container_name, exc.message)
            raise

    # ── delete_item (replaces Cosmos DB table.delete_item) ─────────────────────

    def delete_item(self, key_dict: Dict[str, Any]) -> None:
        """
        Delete a document by its key.
        """
        item_id, partition_key = self._extract_key(key_dict)

        try:
            self.container.delete_item(item=item_id, partition_key=partition_key)
            logger.info("delete_item: %s id=%s", self.container_name, item_id)

        except CosmosResourceNotFoundError:
            logger.warning(
                "delete_item: %s id=%s — not found (already deleted?)",
                self.container_name, item_id,
            )
        except CosmosHttpResponseError as exc:
            logger.error(
                "delete_item failed on %s: %s", self.container_name, exc.message
            )
            raise

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_key(key_dict: Dict[str, Any]):
        """
        Extract the item id and partition key value from a legacy-style
        key dict.  By convention the first key is used as both ``id`` and
        partition key.
        """
        values = list(key_dict.values())
        item_id = str(values[0])
        partition_key = values[0]
        return item_id, partition_key

    @staticmethod
    def _strip_system_properties(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Remove Cosmos DB internal system properties (_rid, _self, etc.)."""
        return {
            k: v for k, v in doc.items()
            if not k.startswith("_") or k == "_ttl"
        }

    @staticmethod
    def _map_ttl_to_cosmos(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Map legacy ``ttl`` field to Cosmos DB ``_ttl`` (seconds)."""
        if "ttl" in doc and "_ttl" not in doc:
            ttl_value = doc.pop("ttl")
            if isinstance(ttl_value, (int, float)):
                now = int(datetime.utcnow().timestamp())
                if ttl_value > now:
                    doc["_ttl"] = int(ttl_value - now)
                else:
                    doc["_ttl"] = 0
            else:
                doc["_ttl"] = int(ttl_value)
        return doc


# ═══════════════════════════════════════════════════════════════════════════════
# Factory helper
# ═══════════════════════════════════════════════════════════════════════════════

# Cache of CosmosDBTable instances by container name
_table_cache: Dict[str, CosmosDBTable] = {}


def get_table(container_name: str) -> CosmosDBTable:
    """
    Return a ``CosmosDBTable`` for the given container, caching instances.

    Args:
        container_name: Cosmos DB container name.

    Returns:
        CosmosDBTable instance.
    """
    if container_name not in _table_cache:
        _table_cache[container_name] = CosmosDBTable(container_name)
    return _table_cache[container_name]
