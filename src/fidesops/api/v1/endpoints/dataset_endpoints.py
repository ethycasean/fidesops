import logging
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from fastapi.params import Security
from fastapi_pagination import Page, Params
from fastapi_pagination.bases import AbstractPage
from fastapi_pagination.ext.sqlalchemy import paginate
from pydantic import conlist
from sqlalchemy.orm import Session
from fidesops.common_exceptions import ValidationError

from fidesops.common_exceptions import TraversalError
from starlette.status import HTTP_404_NOT_FOUND

from fidesops.api import deps
from fidesops.api.v1.scope_registry import (
    DATASET_READ,
    DATASET_CREATE_OR_UPDATE,
    DATASET_DELETE,
)
from fidesops.api.v1.urn_registry import (
    DATASET_VALIDATE,
    DATASETS,
    DATASET_BY_KEY,
    V1_URL_PREFIX,
)
from fidesops.graph.traversal import DatasetGraph, Traversal
from fidesops.models.connectionconfig import ConnectionConfig
from fidesops.models.datasetconfig import DatasetConfig, convert_dataset_to_graph
from fidesops.schemas.api import (
    BulkUpdateFailed,
)
from fidesops.schemas.dataset import (
    DatasetTraversalDetails,
    FidesopsDataset,
    ValidateDatasetResponse,
    BulkPutDataset,
)
from fidesops.util.oauth_util import verify_oauth_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Datasets"], prefix=V1_URL_PREFIX)


# Helper method to inject the parent ConnectionConfig into these child routes
def _get_connection_config(
    connection_key: str, db: Session = Depends(deps.get_db)
) -> ConnectionConfig:
    logger.info(f"Finding connection config with key '{connection_key}'")
    connection_config = ConnectionConfig.get_by(db, field="key", value=connection_key)
    if not connection_config:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"No connection config with key '{connection_key}'",
        )
    return connection_config


@router.put(
    DATASET_VALIDATE,
    dependencies=[Security(verify_oauth_client, scopes=[DATASET_READ])],
    status_code=200,
    response_model=ValidateDatasetResponse,
)
def validate_dataset(
    dataset: FidesopsDataset,
    connection_config: ConnectionConfig = Depends(_get_connection_config),
) -> ValidateDatasetResponse:
    """
    Run validations against a dataset without attempting to save it to the database.

    Checks that:
    - all required fields are present, all field values are valid types
    - all DataCategory values reference known keys
    - etc.

    After validating, also tests to see if the dataset is traversable. Note that
    it's possible for a dataset to be valid but not traversable; this happens
    when a dataset is dependent on references to other datasets.

    Returns a 200 OK for all valid datasets, and a traversal_details object with
    information about the traversal (or traversal errors).
    """

    try:
        # Attempt to generate a traversal for this dataset by providing an empty
        # dictionary of all unique identity keys
        graph = DatasetGraph(convert_dataset_to_graph(dataset, connection_config.key))
        unique_identities = set(graph.identity_keys.values())
        Traversal(graph, {k: None for k in unique_identities})
    except (TraversalError, ValidationError) as err:
        logger.warning(
            f"Traversal validation failed for dataset '{dataset.fides_key}': {err}"
        )
        return ValidateDatasetResponse(
            dataset=dataset,
            traversal_details=DatasetTraversalDetails(
                is_traversable=False,
                msg=str(err),
            ),
        )

    logger.info(f"Validation successful for dataset '{dataset.fides_key}'!")
    return ValidateDatasetResponse(
        dataset=dataset,
        traversal_details=DatasetTraversalDetails(
            is_traversable=True,
            msg=None,
        ),
    )


@router.put(
    DATASETS,
    dependencies=[Security(verify_oauth_client, scopes=[DATASET_CREATE_OR_UPDATE])],
    status_code=200,
    response_model=BulkPutDataset,
)
def put_datasets(
    datasets: conlist(FidesopsDataset, max_items=50),  # type: ignore
    db: Session = Depends(deps.get_db),
    connection_config: ConnectionConfig = Depends(_get_connection_config),
) -> BulkPutDataset:
    """
    Given a list of dataset elements, create or update corresponding Dataset objects
    or report failure

    Use for bulk creating and/or updating datasets.

    If the fides_key for a given dataset exists, it will be treated as an update.
    Otherwise, a new dataset will be created.
    """

    created_or_updated: List[FidesopsDataset] = []
    failed: List[BulkUpdateFailed] = []
    logger.info(f"Starting bulk upsert for {len(datasets)} datasets")
    for dataset in datasets:
        data = {
            "connection_config_id": connection_config.id,
            "fides_key": dataset.fides_key,
            "dataset": dataset.dict(),
        }
        try:
            # Try to find an existing DatasetConfig matching the given connection & key
            dataset_config = DatasetConfig.create_or_update(db, data=data)
            created_or_updated.append(dataset_config.dataset)
        except Exception:
            logger.warning(f"Create/update failed for dataset '{data['fides_key']}'.")
            failed.append(
                BulkUpdateFailed(
                    message=f"Dataset create/update failed.",
                    data=data,
                )
            )

    return BulkPutDataset(
        succeeded=created_or_updated,
        failed=failed,
    )


@router.get(
    DATASETS,
    dependencies=[Security(verify_oauth_client, scopes=[DATASET_READ])],
    response_model=Page[FidesopsDataset],
)
def get_datasets(
    db: Session = Depends(deps.get_db),
    params: Params = Depends(),
    connection_config: ConnectionConfig = Depends(_get_connection_config),
) -> AbstractPage[FidesopsDataset]:
    """Returns all datasets in the database."""

    logger.info(
        f"Finding all datasets for connection '{connection_config.key}' with pagination params {params}"
    )
    dataset_configs = DatasetConfig.filter(
        db=db, conditions=(DatasetConfig.connection_config_id == connection_config.id)
    )

    # Generate the paginated results, but don't return them as-is. Instead,
    # modify the items array to be just the FidesopsDataset instead of the full
    # DatasetConfig. This has to be done *afterwards* to ensure that the
    # paginated query is handled by paginate()
    paginated_results = paginate(dataset_configs, params=params)
    paginated_results.items = [
        dataset_config.dataset for dataset_config in paginated_results.items
    ]
    return paginated_results


@router.get(
    DATASET_BY_KEY,
    dependencies=[Security(verify_oauth_client, scopes=[DATASET_READ])],
    response_model=FidesopsDataset,
)
def get_dataset(
    fides_key: str,
    db: Session = Depends(deps.get_db),
    connection_config: ConnectionConfig = Depends(_get_connection_config),
) -> FidesopsDataset:
    """Returns a single dataset based on the given key."""

    logger.info(
        f"Finding dataset '{fides_key}' for connection '{connection_config.key}'"
    )
    dataset_config = DatasetConfig.filter(
        db=db,
        conditions=(
            (DatasetConfig.connection_config_id == connection_config.id)
            & (DatasetConfig.fides_key == fides_key)
        ),
    ).first()
    if not dataset_config:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"No dataset with fides_key '{fides_key}' and connection key {connection_config.key}'",
        )
    return dataset_config.dataset


@router.delete(
    DATASET_BY_KEY,
    dependencies=[Security(verify_oauth_client, scopes=[DATASET_DELETE])],
    status_code=204,
)
def delete_dataset(
    fides_key: str,
    *,
    db: Session = Depends(deps.get_db),
    connection_config: ConnectionConfig = Depends(_get_connection_config),
) -> None:
    """Removes the dataset based on the given key."""

    logger.info(
        f"Finding dataset '{fides_key}' for connection '{connection_config.key}'"
    )
    dataset_config = DatasetConfig.filter(
        db=db,
        conditions=(
            (DatasetConfig.connection_config_id == connection_config.id)
            & (DatasetConfig.fides_key == fides_key)
        ),
    ).first()
    if not dataset_config:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"No dataset with fides_key '{fides_key}' and connection_key '{connection_config.key}'",
        )

    logger.info(
        f"Deleting dataset '{fides_key}' for connection '{connection_config.key}'"
    )
    dataset_config.delete(db)
