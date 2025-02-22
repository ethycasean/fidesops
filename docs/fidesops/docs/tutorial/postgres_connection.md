# Connect to the Flask App Database

## Creating a Postgres ConnectionConfig

For more detailed information, [see the Database Connectors Guide](../guides/database_connectors.md).

---

Next, we need to create a ConnectionConfig so fidesops can connect to our Flask App's  database.

Let's add a method that hits the PUT `connection` endpoint, and creates a ConnectionConfig for a `postgres` database:

### Define helper methods

```python
def create_postgres_connection(key, access_token):
    """
    Create a connection in fidesops for our PostgreSQL database. Returns the response JSON if successful.
    See http://localhost:8000/docs#/Connections/put_connections_api_v1_connection_put
    """
    connection_create_data = [
        {
            "name": key,
            "key": key,
            "connection_type": "postgres",
            "access": "write",
        },
    ]
    response = requests.put(
        f"{FIDESOPS_URL}/api/v1/connection",
        headers=oauth_headers(access_token=access_token),
        json=connection_create_data,
    )
    logger.info(f"Creating PostgreSQL ConnectionConfig. Status {response.status_code}")
    return response.json()

```

Secrets, like a username and password that are needed to access the Flask App's databases, are added separately:

```python
def configure_postgres_connection(
    key, host, port, dbname, username, password, access_token
):
    """
    Configure the connection with the given `key` in fidesops with our PostgreSQL database credentials. Returns the response JSON if successful.
    See http://localhost:8000/docs#/Connections/put_connection_config_secrets_api_v1_connection__connection_key__secret_put
    """
    connection_secrets_data = {
        "host": host,
        "port": port,
        "dbname": dbname,
        "username": username,
        "password": password,
    }
    response = requests.put(
        f"{FIDESOPS_URL}/api/v1/connection/{key}/secret",
        headers=oauth_headers(access_token=access_token),
        json=connection_secrets_data,
    )
    logger.info(f"Updating PostgreSQL Secrets. Status {response.status_code}.")
    return response.json()

```

### Call helper methods to connect to Postgres

Add calls for our new methods, to create a Postgres ConnectionConfig called `flaskr-postgres`, and 
then update that connection's secrets with individual URI components.  This will encrypt and save the URI components 
and also attempt to make a test connection to our Flask App's Postgres Database.
```python

if __name__ == "__main__":
    ...
    # Connect to our PostgreSQL database
    create_postgres_connection(key="flaskr-postgres", access_token=access_token)

    configure_postgres_connection(
        key="flaskr-postgres",
        host=POSTGRES_SERVER,
        port=POSTGRES_PORT,
        dbname="flaskr",
        username=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        access_token=access_token,
    )
    ...
```