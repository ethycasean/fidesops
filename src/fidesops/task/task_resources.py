import logging
from typing import Dict, Any, Optional, List

from fidesops.common_exceptions import ConnectorNotFoundException
from fidesops.db.session import get_db_session
from fidesops.graph.config import (
    CollectionAddress,
)
from fidesops.models.connectionconfig import ConnectionConfig, ConnectionType
from fidesops.models.policy import ActionType, Policy
from fidesops.models.privacy_request import ExecutionLog, ExecutionLogStatus
from fidesops.models.privacy_request import PrivacyRequest
from fidesops.service.connectors import (
    BaseConnector,
    PostgreSQLConnector,
    MongoDBConnector,
    MySQLConnector,
)
from fidesops.util.cache import get_cache

logger = logging.getLogger(__name__)


class Connections:
    """Temporary container for connections. This will be replaced."""

    def __init__(self) -> None:
        self.connections: Dict[str, BaseConnector] = {}

    def get_connector(self, connection_config: ConnectionConfig) -> BaseConnector:
        """Return the connector corresponding to this config. Will return the existing
        connector or create one if it does not yet exist."""
        key = connection_config.key
        if key not in self.connections:
            connector = Connections.build_connector(connection_config)
            self.connections[key] = connector
        return self.connections[key]

    @staticmethod
    def build_connector(connection_config: ConnectionConfig) -> BaseConnector:
        """Factory method to build the appropriately typed connector from the config."""
        if connection_config.connection_type == ConnectionType.postgres:
            return PostgreSQLConnector(connection_config)
        if connection_config.connection_type == ConnectionType.mongodb:
            return MongoDBConnector(connection_config)
        if connection_config.connection_type == ConnectionType.mysql:
            return MySQLConnector(connection_config)
        raise NotImplementedError(
            f"No connector available for {connection_config.connection_type}"
        )


class TaskResources:
    """Shared information and environment for all nodes of a given task.
    This includes
     - the privacy request
     - the policy
     - redis connection
     -  configurations to any outside resources the task will require to run
    """

    def __init__(
        self,
        request: PrivacyRequest,
        policy: Policy,
        connection_configs: List[ConnectionConfig],
    ):
        self.request = request
        self.policy = policy
        self.cache = get_cache()
        # tbd populate connection configurations.
        self.connection_configs: Dict[str, ConnectionConfig] = {
            c.key: c for c in connection_configs
        }
        self.connections = Connections()

    def cache_object(self, key: str, value: Any) -> None:
        """Store in cache. Object will be
        stored in redis under 'REQUEST_ID__TYPE__ADDRESS'"""
        self.cache.set_encoded_object(f"{self.request.id}__{key}", value)

    def get_all_cached_objects(self) -> Dict[str, Optional[Any]]:
        """Retrieve the results of all steps"""
        value_dict = self.cache.get_encoded_objects_by_prefix(self.request.id)
        # extract request id to return a map of address:value
        return {k.split("__")[-1]: v for k, v in value_dict.items()}

    def write_execution_log(  # pylint: disable=too-many-arguments
        self,
        collection_address: CollectionAddress,
        fields_affected: Any,
        action_type: ActionType,
        status: ExecutionLogStatus,
        message: str = None,
    ) -> Any:
        """Store in application db. Return the created or written-to id field value."""
        SessionLocal = get_db_session()
        db = SessionLocal()

        ExecutionLog.create(
            db=db,
            data={
                "dataset_name": collection_address.dataset,
                "collection_name": collection_address.collection,
                "fields_affected": fields_affected,
                "action_type": action_type,
                "status": status,
                "privacy_request_id": self.request.id,
                "message": message,
            },
        )
        db.close()

    def get_connector(self, key: str) -> Any:
        """Create or return the client corresponding to the given ConnectionConfig key"""
        if key in self.connection_configs:
            return self.connections.get_connector(self.connection_configs[key])
        raise ConnectorNotFoundException(f"No available connector for {key}")
