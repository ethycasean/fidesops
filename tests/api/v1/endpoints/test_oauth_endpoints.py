from datetime import datetime
import json
import pytest

from starlette.testclient import TestClient

from fidesops.api.v1.scope_registry import (
    SCOPE_REGISTRY,
    CLIENT_DELETE,
    CLIENT_READ,
    STORAGE_READ,
    CLIENT_CREATE,
    SCOPE_READ,
    CLIENT_UPDATE,
)
from fidesops.api.v1.urn_registry import (
    CLIENT,
    CLIENT_BY_ID,
    CLIENT_SCOPE,
    TOKEN,
    V1_URL_PREFIX,
    SCOPE,
)
from fidesops.models.client import ClientDetail
from fidesops.schemas.jwt import (
    JWE_PAYLOAD_CLIENT_ID,
    JWE_PAYLOAD_SCOPES,
    JWE_ISSUED_AT,
)
from fidesops.util.oauth_util import extract_payload, generate_jwe


class TestCreateClient:
    @pytest.fixture(scope="function")
    def url(self, oauth_client) -> str:
        return V1_URL_PREFIX + CLIENT

    def test_create_client_not_authenticated(self, api_client: TestClient, url):
        response = api_client.post(url)
        assert response.status_code == 401

    def test_create_client_wrong_scope(
        self, api_client: TestClient, url, generate_auth_header
    ) -> None:
        auth_header = generate_auth_header([CLIENT_READ])
        response = api_client.post(url, headers=auth_header)
        assert 403 == response.status_code

    def test_create_client_lacks_client(self, api_client: TestClient, url) -> None:
        payload = {
            JWE_PAYLOAD_SCOPES: [CLIENT_CREATE],
        }
        # Build auth header without client
        auth_header = {"Authorization": "Bearer " + generate_jwe(json.dumps(payload))}

        response = api_client.post(url, headers=auth_header)
        assert 403 == response.status_code

    def test_create_client_with_expired_token(
        self, api_client: TestClient, url, oauth_client
    ):
        payload = {
            JWE_PAYLOAD_CLIENT_ID: oauth_client.id,
            JWE_PAYLOAD_SCOPES: oauth_client.scopes,
            JWE_ISSUED_AT: datetime(1995, 1, 1).isoformat(),
        }
        auth_header = {"Authorization": "Bearer " + generate_jwe(json.dumps(payload))}
        response = api_client.post(url, headers=auth_header)
        assert 403 == response.status_code

    def test_create_client(
        self,
        db,
        api_client: TestClient,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_CREATE])

        response = api_client.post(url, headers=auth_header)
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert list(response_body.keys()) == ["client_id", "client_secret"]

        new_client = ClientDetail.get(db, id=response_body["client_id"])
        assert new_client.hashed_secret != response_body["client_secret"]

        new_client.delete(db)

    def test_create_client_with_scopes(
        self,
        db,
        api_client: TestClient,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_CREATE])

        scopes = [
            CLIENT_CREATE,
            CLIENT_DELETE,
            CLIENT_READ,
        ]
        response = api_client.post(
            url,
            headers=auth_header,
            json=scopes,
        )
        response_body = json.loads(response.text)
        assert 200 == response.status_code
        assert list(response_body.keys()) == ["client_id", "client_secret"]

        new_client = ClientDetail.get(db, id=response_body["client_id"])
        assert new_client.scopes == scopes

        new_client.delete(db)

    def test_create_client_with_invalid_scopes(
        self,
        api_client: TestClient,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_CREATE])

        response = api_client.post(
            url,
            headers=auth_header,
            json=["invalid-scope"],
        )

        assert 422 == response.status_code
        assert response.json()["detail"].startswith("Invalid Scope.")


class TestGetClientScopes:
    @pytest.fixture(scope="function")
    def url(self, oauth_client) -> str:
        return V1_URL_PREFIX + CLIENT_SCOPE.format(client_id=oauth_client.id)

    def test_get_scopes_not_authenticated(
        self, api_client: TestClient, oauth_client: ClientDetail, url
    ):
        response = api_client.get(url)
        assert response.status_code == 401

    def test_get_scopes_wrong_scope(
        self,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([STORAGE_READ])
        response = api_client.get(url, headers=auth_header)
        assert 403 == response.status_code

    def test_get_scopes_invalid_client(
        self, api_client: TestClient, oauth_client: ClientDetail, generate_auth_header
    ) -> None:
        url = V1_URL_PREFIX + CLIENT_SCOPE.format(client_id="bad_client")

        auth_header = generate_auth_header([CLIENT_READ])
        response = api_client.get(url, headers=auth_header)
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert response_body == []

    def test_get_scopes(
        self,
        db,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_READ])

        response = api_client.get(url, headers=auth_header)
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert response_body == SCOPE_REGISTRY


class TestSetClientScopes:
    @pytest.fixture(scope="function")
    def url(self, oauth_client) -> str:
        return V1_URL_PREFIX + CLIENT_SCOPE.format(client_id=oauth_client.id)

    def test_set_scopes_not_authenticated(
        self, api_client: TestClient, oauth_client: ClientDetail, url
    ):
        response = api_client.put(url)
        assert response.status_code == 401

    def test_set_scopes_wrong_scope(
        self,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_READ])
        response = api_client.put(url, headers=auth_header)
        assert 403 == response.status_code

    def test_set_invalid_scope(
        self,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_UPDATE])

        response = api_client.put(
            url, headers=auth_header, json=["this-is-not-a-valid-scope"]
        )
        assert 422 == response.status_code

    def test_set_scopes_invalid_client(
        self, api_client: TestClient, oauth_client: ClientDetail, generate_auth_header
    ) -> None:
        url = V1_URL_PREFIX + CLIENT_SCOPE.format(client_id="bad_client")

        auth_header = generate_auth_header([CLIENT_UPDATE])
        response = api_client.put(url, headers=auth_header, json=["storage:read"])
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert response_body is None  # No action was taken

    def test_set_scopes(
        self,
        db,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_UPDATE])

        response = api_client.put(url, headers=auth_header, json=["storage:read"])
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert response_body is None

        db.refresh(oauth_client)
        assert oauth_client.scopes == ["storage:read"]


class TestReadScopes:
    @pytest.fixture(scope="function")
    def url(self, oauth_client) -> str:
        return V1_URL_PREFIX + SCOPE

    def test_get_scopes_not_authenticated(self, api_client: TestClient, url):
        response = api_client.get(url)
        assert response.status_code == 401

    def test_get_scopes_wrong_scope(
        self,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([STORAGE_READ])
        response = api_client.get(url, headers=auth_header)
        assert 403 == response.status_code

    def test_get_scopes(
        self,
        db,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([SCOPE_READ])

        response = api_client.get(url, headers=auth_header)
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert response_body == SCOPE_REGISTRY


class TestDeleteClient:
    @pytest.fixture(scope="function")
    def url(self, oauth_client) -> str:
        return V1_URL_PREFIX + CLIENT_BY_ID.format(client_id=oauth_client.id)

    def test_delete_client_not_authenticated(
        self, api_client: TestClient, oauth_client: ClientDetail, url
    ):
        response = api_client.delete(url)
        assert response.status_code == 401

    def test_delete_client_wrong_scope(
        self,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_READ])
        response = api_client.delete(url, headers=auth_header)
        assert 403 == response.status_code

    def test_delete_client_invalid_client(
        self, api_client: TestClient, oauth_client: ClientDetail, generate_auth_header
    ) -> None:
        url = V1_URL_PREFIX + CLIENT_BY_ID.format(client_id="bad_client")

        auth_header = generate_auth_header([CLIENT_DELETE])
        response = api_client.delete(url, headers=auth_header)
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert response_body is None  # No indicator that client didn't exist

    def test_delete_client(
        self,
        db,
        api_client: TestClient,
        oauth_client: ClientDetail,
        url,
        generate_auth_header,
    ) -> None:
        auth_header = generate_auth_header([CLIENT_DELETE])

        response = api_client.delete(url, headers=auth_header)
        response_body = json.loads(response.text)

        assert 200 == response.status_code
        assert response_body is None

        db.expunge_all()
        client = ClientDetail.get(db, id=oauth_client.id)
        assert client is None


class TestAcquireAccessToken:
    @pytest.fixture(scope="function")
    def url(self, oauth_client) -> str:
        return V1_URL_PREFIX + TOKEN

    def test_no_form_data(self, db, url, api_client):
        response = api_client.post(url, data={})
        assert response.status_code == 401

    def test_invalid_client(self, db, url, api_client):
        response = api_client.post(
            url, data={"client_id": "notaclient", "secret": "badsecret"}
        )
        assert response.status_code == 401

    def test_invalid_client_secret(self, db, url, api_client):
        new_client, _ = ClientDetail.create_client_and_secret(db)
        response = api_client.post(
            url, data={"client_id": new_client.id, "secret": "badsecret"}
        )
        assert response.status_code == 401

        new_client.delete(db)

    def test_get_access_token(self, db, url, api_client):
        new_client, secret = ClientDetail.create_client_and_secret(db)

        data = {
            "client_id": new_client.id,
            "client_secret": secret,
        }

        response = api_client.post(url, data=data)
        jwt = json.loads(response.text).get("access_token")
        assert 200 == response.status_code
        assert (
            data["client_id"] == json.loads(extract_payload(jwt))[JWE_PAYLOAD_CLIENT_ID]
        )
        assert json.loads(extract_payload(jwt))[JWE_PAYLOAD_SCOPES] == []

        new_client.delete(db)
