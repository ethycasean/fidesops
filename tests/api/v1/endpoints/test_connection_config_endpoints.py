import json
from typing import Dict, List
from unittest import mock
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi_pagination import Params
from starlette.testclient import TestClient

from fidesops.models.client import ClientDetail
from fidesops.models.connectionconfig import ConnectionConfig
from fidesops.api.v1.scope_registry import (
    CONNECTION_CREATE_OR_UPDATE,
    STORAGE_DELETE,
    CONNECTION_READ,
    CONNECTION_DELETE,
)

from sqlalchemy.orm import Session

from fidesops.api.v1.urn_registry import CONNECTIONS, V1_URL_PREFIX

page_size = Params().size


class TestPutConnections:
    @pytest.fixture(scope="function")
    def url(self, oauth_client: ClientDetail, policy) -> str:
        return V1_URL_PREFIX + CONNECTIONS

    @pytest.fixture(scope="function")
    def payload(self) -> List[Dict[str, str]]:
        return [
            {
                "name": "My Main Postgres DB",
                "key": "postgres db 1",
                "connection_type": "postgres",
                "access": "write",
            },
            {"name": "My Mongo DB", "connection_type": "mongodb", "access": "read"},
        ]

    def test_put_connections_not_authenticated(
        self, api_client: TestClient, generate_auth_header, url, payload
    ) -> None:
        response = api_client.put(url, headers={}, json=payload)
        assert 401 == response.status_code

    def test_put_connections_incorrect_scope(
        self, api_client: TestClient, generate_auth_header, url, payload
    ) -> None:
        auth_header = generate_auth_header(scopes=[STORAGE_DELETE])
        response = api_client.put(url, headers=auth_header, json=payload)
        assert 403 == response.status_code

    def test_put_connections_add_secret_invalid(
        self, api_client: TestClient, generate_auth_header, url
    ) -> None:
        payload_with_secrets = [
            {
                "name": "My Main Postgres DB",
                "key": "postgres-db-1",
                "connection_type": "postgres",
                "access": "write",
                "secrets": {"host": "localhost"},
            },
            {"name": "My Mongo DB", "connection_type": "mongodb", "access": "read"},
        ]
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        response = api_client.put(url, headers=auth_header, json=payload_with_secrets)
        assert 422 == response.status_code
        response_body = json.loads(response.text)
        assert "extra fields not permitted" == response_body["detail"][0]["msg"]

    def test_put_connections_bulk_create(
        self, api_client: TestClient, db: Session, generate_auth_header, url, payload
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        response = api_client.put(url, headers=auth_header, json=payload)

        assert 200 == response.status_code
        response_body = json.loads(response.text)
        assert len(response_body) == 2
        assert len(response_body["succeeded"]) == 2

        postgres_connection = response_body["succeeded"][0]
        postgres_resource = (
            db.query(ConnectionConfig).filter_by(key="postgres-db-1").first()
        )
        assert postgres_connection["name"] == "My Main Postgres DB"
        assert postgres_connection["key"] == "postgres-db-1"
        assert postgres_connection["connection_type"] == "postgres"
        assert postgres_connection["access"] == "write"
        assert postgres_connection["created_at"] is not None
        assert postgres_connection["updated_at"] is not None
        assert postgres_connection["last_test_timestamp"] is None
        assert "secrets" not in postgres_connection

        mongo_connection = response_body["succeeded"][1]
        mongo_resource = db.query(ConnectionConfig).filter_by(key="my-mongo-db").first()
        assert mongo_connection["name"] == "My Mongo DB"
        assert mongo_connection["key"] == "my-mongo-db"  # stringified name
        assert mongo_connection["connection_type"] == "mongodb"
        assert mongo_connection["access"] == "read"
        assert mongo_connection["created_at"] is not None
        assert mongo_connection["updated_at"] is not None
        assert mongo_connection["last_test_timestamp"] is None
        assert "secrets" not in mongo_connection

        assert response_body["failed"] == []  # No failures

        postgres_resource.delete(db)
        mongo_resource.delete(db)

    def test_put_connections_bulk_update_key_error(
        self, url, api_client: TestClient, db: Session, generate_auth_header, payload
    ) -> None:
        # Create resources first
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        api_client.put(url, headers=auth_header, json=payload)

        # Update resources
        response = api_client.put(url, headers=auth_header, json=payload)

        assert response.status_code == 200
        response_body = json.loads(response.text)
        assert len(response_body["succeeded"]) == 0
        assert len(response_body["failed"]) == 2

        failed = response_body["failed"]
        # non-slugified key was supplied in request body, which turned into a key that exists
        assert failed[0]["data"]["key"] == "postgres db 1"
        assert (
            "Key postgres-db-1 already exists in ConnectionConfig"
            in failed[0]["message"]
        )
        # No key was supplied in request body, just a name, and that name turned into a key that exists
        assert failed[1]["data"]["key"] is None
        assert (
            "Key my-mongo-db already exists in ConnectionConfig" in failed[1]["message"]
        )

    def test_put_connections_bulk_create_limit_exceeded(
        self, url, api_client: TestClient, db: Session, generate_auth_header
    ):
        payload = []
        for i in range(0, 51):
            payload.append(
                {
                    "name": f"My Main Postgres DB {i}",
                    "key": f"postgres-db-{i}",
                    "connection_type": "postgres",
                    "access": "read",
                }
            )

        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        response = api_client.put(url, headers=auth_header, json=payload)
        assert 422 == response.status_code
        assert (
            json.loads(response.text)["detail"][0]["msg"]
            == "ensure this value has at most 50 items"
        )

    def test_put_connections_bulk_update(
        self, url, api_client: TestClient, db: Session, generate_auth_header, payload
    ) -> None:
        # Create resources first
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        api_client.put(url, headers=auth_header, json=payload)

        # Update resources
        payload = [
            {
                "name": "My Main Postgres DB",
                "key": "postgres-db-1",
                "connection_type": "postgres",
                "access": "read",
            },
            {
                "key": "my-mongo-db",
                "name": "My Mongo DB",
                "connection_type": "mongodb",
                "access": "write",
            },
            {
                "key": "my-redshift-cluster",
                "name": "My Amazon Redshift",
                "connection_type": "redshift",
                "access": "read",
            },
            {
                "key": "my-snowflake",
                "name": "Snowflake Warehouse",
                "connection_type": "snowflake",
                "access": "write",
            },
        ]

        response = api_client.put(
            V1_URL_PREFIX + CONNECTIONS, headers=auth_header, json=payload
        )

        assert 200 == response.status_code
        response_body = json.loads(response.text)
        assert len(response_body) == 2
        assert len(response_body["succeeded"]) == 4
        assert len(response_body["failed"]) == 0

        postgres_connection = response_body["succeeded"][0]
        assert postgres_connection["access"] == "read"
        assert "secrets" not in postgres_connection
        assert postgres_connection["updated_at"] is not None
        postgres_resource = (
            db.query(ConnectionConfig).filter_by(key="postgres-db-1").first()
        )
        assert postgres_resource.access.value == "read"

        mongo_connection = response_body["succeeded"][1]
        assert mongo_connection["access"] == "write"
        assert mongo_connection["updated_at"] is not None
        mongo_resource = db.query(ConnectionConfig).filter_by(key="my-mongo-db").first()
        assert mongo_resource.access.value == "write"
        assert "secrets" not in mongo_connection

        redshift_connection = response_body["succeeded"][2]
        assert redshift_connection["access"] == "read"
        assert redshift_connection["updated_at"] is not None
        redshift_resource = (
            db.query(ConnectionConfig).filter_by(key="my-redshift-cluster").first()
        )
        assert redshift_resource.access.value == "read"
        assert "secrets" not in redshift_connection

        snowflake_connection = response_body["succeeded"][3]
        assert snowflake_connection["access"] == "write"
        assert snowflake_connection["updated_at"] is not None
        snowflake_resource = (
            db.query(ConnectionConfig).filter_by(key="my-snowflake").first()
        )
        assert snowflake_resource.access.value == "write"
        assert "secrets" not in snowflake_connection

        postgres_resource.delete(db)
        mongo_resource.delete(db)
        redshift_resource.delete(db)
        snowflake_resource.delete(db)

    @mock.patch("fidesops.db.base_class.OrmWrappedFidesopsBase.create_or_update")
    def test_put_connections_failed_response(
        self, mock_create: Mock, api_client: TestClient, generate_auth_header, url
    ) -> None:
        mock_create.side_effect = HTTPException(mock.Mock(status=400), "Test error")

        payload = [
            {
                "name": "My Main Postgres DB",
                "key": "postgres-db-1",
                "connection_type": "postgres",
                "access": "write",
            },
            {"name": "My Mongo DB", "connection_type": "mongodb", "access": "read"},
        ]
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        response = api_client.put(url, headers=auth_header, json=payload)
        assert response.status_code == 200  # Returns 200 regardless
        response_body = json.loads(response.text)
        assert response_body["succeeded"] == []
        assert len(response_body["failed"]) == 2

        for failed_response in response_body["failed"]:
            assert (
                "This connection configuration could not be added"
                in failed_response["message"]
            )
            assert set(failed_response.keys()) == {"message", "data"}

        assert response_body["failed"][0]["data"] == {
            "name": "My Main Postgres DB",
            "key": "postgres-db-1",
            "connection_type": "postgres",
            "access": "write",
        }
        assert response_body["failed"][1]["data"] == {
            "name": "My Mongo DB",
            "key": None,
            "connection_type": "mongodb",
            "access": "read",
        }


class TestGetConnections:
    @pytest.fixture(scope="function")
    def url(self, oauth_client: ClientDetail, policy) -> str:
        return V1_URL_PREFIX + CONNECTIONS

    def test_get_connections_not_authenticated(
        self, api_client: TestClient, generate_auth_header, connection_config, url
    ) -> None:
        resp = api_client.get(url, headers={})
        assert resp.status_code == 401

    def test_get_connections_wrong_scope(
        self, api_client: TestClient, generate_auth_header, connection_config, url
    ) -> None:
        auth_header = generate_auth_header(scopes=[STORAGE_DELETE])
        resp = api_client.get(url, headers=auth_header)
        assert resp.status_code == 403

    def test_get_connection_configs(
        self, api_client: TestClient, generate_auth_header, connection_config, url
    ) -> None:
        # Test get connection configs happy path
        auth_header = generate_auth_header(scopes=[CONNECTION_READ])
        resp = api_client.get(url, headers=auth_header)
        assert resp.status_code == 200

        response_body = json.loads(resp.text)
        assert len(response_body["items"]) == 1
        connection = response_body["items"][0]
        assert set(connection.keys()) == {
            "connection_type",
            "access",
            "updated_at",
            "name",
            "last_test_timestamp",
            "last_test_succeeded",
            "key",
            "created_at",
        }

        assert connection["key"] == "my-postgres-db-1"
        assert connection["connection_type"] == "postgres"
        assert connection["access"] == "write"
        assert connection["updated_at"] is not None
        assert connection["last_test_timestamp"] is None

        assert response_body["total"] == 1
        assert response_body["page"] == 1
        assert response_body["size"] == page_size


class TestGetConnection:
    @pytest.fixture(scope="function")
    def url(self, oauth_client: ClientDetail, policy, connection_config) -> str:
        return f"{V1_URL_PREFIX}{CONNECTIONS}/{connection_config.key}"

    def test_get_connection_not_authenticated(
        self, url, api_client: TestClient, connection_config
    ) -> None:
        resp = api_client.get(url, headers={})
        assert resp.status_code == 401

    def test_get_connection_wrong_scope(
        self, url, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        auth_header = generate_auth_header(scopes=[STORAGE_DELETE])
        resp = api_client.get(url, headers=auth_header)
        assert resp.status_code == 403

    def test_get_connection_does_not_exist(
        self, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_READ])
        resp = api_client.get(
            f"{V1_URL_PREFIX}{CONNECTIONS}/this-is-a-nonexistant-key",
            headers=auth_header,
        )
        assert resp.status_code == 404

    def test_get_connection_config(
        self, url, api_client: TestClient, generate_auth_header, connection_config
    ):
        auth_header = generate_auth_header(scopes=[CONNECTION_READ])
        resp = api_client.get(url, headers=auth_header)
        assert resp.status_code == 200

        response_body = json.loads(resp.text)
        assert set(response_body.keys()) == {
            "connection_type",
            "access",
            "updated_at",
            "name",
            "last_test_timestamp",
            "last_test_succeeded",
            "key",
            "created_at",
        }

        assert response_body["key"] == "my-postgres-db-1"
        assert response_body["connection_type"] == "postgres"
        assert response_body["access"] == "write"
        assert response_body["updated_at"] is not None
        assert response_body["last_test_timestamp"] is None


class TestDeleteConnection:
    @pytest.fixture(scope="function")
    def url(self, oauth_client: ClientDetail, policy, connection_config) -> str:
        return f"{V1_URL_PREFIX}{CONNECTIONS}/{connection_config.key}"

    def test_delete_connection_config_not_authenticated(
        self, url, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        # Test not authenticated
        resp = api_client.delete(url, headers={})
        assert resp.status_code == 401

    def test_delete_connection_config_wrong_scope(
        self, url, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_READ])
        resp = api_client.delete(url, headers=auth_header)
        assert resp.status_code == 403

    def test_delete_connection_config_does_not_exist(
        self, api_client: TestClient, generate_auth_header
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_DELETE])
        resp = api_client.delete(
            f"{V1_URL_PREFIX}{CONNECTIONS}/non-existent-config", headers=auth_header
        )
        assert resp.status_code == 404

    def test_delete_connection_config(
        self,
        url,
        api_client: TestClient,
        db: Session,
        generate_auth_header,
        connection_config,
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_DELETE])
        resp = api_client.delete(url, headers=auth_header)
        assert resp.status_code == 204

        assert (
            db.query(ConnectionConfig).filter_by(key=connection_config.key).first()
            is None
        )


class TestPutConnectionConfigSecrets:
    @pytest.fixture(scope="function")
    def url(self, oauth_client: ClientDetail, policy, connection_config) -> str:
        return f"{V1_URL_PREFIX}{CONNECTIONS}/{connection_config.key}/secret"

    def test_put_connection_config_secrets_not_authenticated(
        self, url, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        resp = api_client.put(url, headers={})
        assert resp.status_code == 401

    def test_put_connection_config_secrets_wrong_scope(
        self, url, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_READ])
        resp = api_client.put(
            url,
            headers=auth_header,
        )
        assert resp.status_code == 403

    def test_put_connection_config_secrets_invalid_config(
        self, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        resp = api_client.put(
            f"{V1_URL_PREFIX}{CONNECTIONS}/this-is-not-a-known-key/secret",
            headers=auth_header,
            json={}
        )
        assert resp.status_code == 404

    def test_put_connection_config_secrets_schema_validation(
        self, url, api_client: TestClient, generate_auth_header, connection_config
    ) -> None:
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        payload = {"incorrect_postgres_uri_component": "test-1"}
        resp = api_client.put(
            url,
            headers=auth_header,
            json=payload,
        )
        assert resp.status_code == 422
        assert json.loads(resp.text)["detail"][0]["msg"] == "extra fields not permitted"

        payload = {"dbname": "my_db"}
        resp = api_client.put(
            url,
            headers=auth_header,
            json=payload,
        )
        assert resp.status_code == 422
        assert (
            json.loads(resp.text)["detail"][0]["msg"]
            == "PostgreSQLSchema must be supplied a 'url' or all of: ['host']."
        )

        payload = {"port": "cannot be turned into an integer"}
        resp = api_client.put(
            url,
            headers=auth_header,
            json=payload,
        )
        assert resp.status_code == 422
        assert (
            json.loads(resp.text)["detail"][0]["msg"] == "value is not a valid integer"
        )

    def test_put_connection_config_secrets(
        self,
        url,
        api_client: TestClient,
        db: Session,
        generate_auth_header,
        connection_config,
    ) -> None:
        """Note: this test does not attempt to actually connect to the db, via use of verify query param."""
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        payload = {"host": "localhost", "port": "1234", "dbname": "my_test_db"}
        resp = api_client.put(
            url + "?verify=False",
            headers=auth_header,
            json=payload,
        )
        assert resp.status_code == 200
        assert (
            json.loads(resp.text)["msg"]
            == f"Secrets updated for ConnectionConfig with key: {connection_config.key}."
        )
        db.refresh(connection_config)
        assert connection_config.secrets == {
            "host": "localhost",
            "port": 1234,
            "dbname": "my_test_db",
            "username": None,
            "password": None,
            "url": None,
        }

        payload = {"url": "postgresql://test_user:test_pass@localhost:1234/my_test_db"}
        resp = api_client.put(
            url + "?verify=False",
            headers=auth_header,
            json=payload,
        )
        assert resp.status_code == 200
        assert (
            json.loads(resp.text)["msg"]
            == f"Secrets updated for ConnectionConfig with key: {connection_config.key}."
        )
        db.refresh(connection_config)
        assert connection_config.secrets == {
            "host": None,
            "port": None,
            "dbname": None,
            "username": None,
            "password": None,
            "url": payload["url"],
        }
        assert connection_config.last_test_timestamp is None
        assert connection_config.last_test_succeeded is None

    def test_put_connection_config_redshift_secrets(
        self,
        api_client: TestClient,
        db: Session,
        generate_auth_header,
        redshift_connection_config,
    ) -> None:
        """Note: this test does not attempt to actually connect to the db, via use of verify query param."""
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        url = f"{V1_URL_PREFIX}{CONNECTIONS}/{redshift_connection_config.key}/secret"
        payload = {
            "host": "examplecluster.abc123xyz789.us-west-1.redshift.amazonaws.com",
            "port": 5439,
            "database": "dev",
            "user": "awsuser",
            "password": "test_password",
        }
        resp = api_client.put(
            url + "?verify=False",
            headers=auth_header,
            json=payload,
        )
        assert resp.status_code == 200
        assert (
            json.loads(resp.text)["msg"]
            == f"Secrets updated for ConnectionConfig with key: {redshift_connection_config.key}."
        )
        db.refresh(redshift_connection_config)
        assert redshift_connection_config.secrets == {
            "host": "examplecluster.abc123xyz789.us-west-1.redshift.amazonaws.com",
            "port": 5439,
            "database": "dev",
            "user": "awsuser",
            "password": "test_password",
            "url": None,
        }
        assert redshift_connection_config.last_test_timestamp is None
        assert redshift_connection_config.last_test_succeeded is None

    def test_put_connection_config_snowflake_secrets(
        self,
        api_client: TestClient,
        db: Session,
        generate_auth_header,
        snowflake_connection_config,
    ) -> None:
        """Note: this test does not attempt to actually connect to the db, via use of verify query param."""
        auth_header = generate_auth_header(scopes=[CONNECTION_CREATE_OR_UPDATE])
        url = f"{V1_URL_PREFIX}{CONNECTIONS}/{snowflake_connection_config.key}/secret"
        payload = {
            "user_login_name": "test_user",
            "password": "test_password",
            "account_identifier": "flso2222test",
            "database_name": "test",
        }

        resp = api_client.put(
            url + "?verify=False",
            headers=auth_header,
            json=payload,
        )
        assert resp.status_code == 200
        assert (
            json.loads(resp.text)["msg"]
            == f"Secrets updated for ConnectionConfig with key: {snowflake_connection_config.key}."
        )
        db.refresh(snowflake_connection_config)
        assert snowflake_connection_config.secrets == {
            "user_login_name": "test_user",
            "password": "test_password",
            "account_identifier": "flso2222test",
            "database_name": "test",
            "schema_name": None,
            "warehouse_name": None,
            "role_name": None,
            "url": None,
        }
        assert snowflake_connection_config.last_test_timestamp is None
        assert snowflake_connection_config.last_test_succeeded is None
