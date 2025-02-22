import json
import logging
import os
from datetime import datetime
from typing import Any, Optional, Dict

from fidesops.models.privacy_request import PrivacyRequest
from fidesops.schemas.storage.storage import (
    StorageType,
    FileNaming,
    StorageDetails,
    ResponseFormat,
)
from sqlalchemy.orm import Session
from fidesops.models.storage import StorageConfig
from fidesops.tasks.storage import upload_to_s3, upload_to_onetrust
from fidesops.common_exceptions import StorageUploadError


logger = logging.getLogger(__name__)


LOCAL_FIDES_UPLOAD_DIRECTORY = "fides_uploads"


def upload(db: Session, *, request_id: str, data: Dict, storage_key: str) -> str:
    """Retrieves storage configs and calls appropriate upload method"""
    config: Optional[StorageConfig] = StorageConfig.get_by(
        db=db, field="key", value=storage_key
    )

    if config is None:
        logger.warning(f"Storage type not found: {storage_key}")
        raise StorageUploadError(f"Storage type not found: {storage_key}")
    if config.secrets is None and config.type != StorageType.local:
        logger.warning(f"Storage secrets not found: {storage_key}")
        raise StorageUploadError(f"Storage secrets not found")
    uploader: Any = _get_uploader_from_config_type(config.type)
    return uploader(db, config, data, request_id)


def get_extension(resp_format: ResponseFormat) -> str:
    """
    Determine file extension for various response formats.

    CSV's are zipped together before uploading to s3.
    """
    if resp_format == ResponseFormat.csv:
        return "zip"

    if resp_format == ResponseFormat.json:
        return "json"

    raise NotImplementedError(f"No extension defined for {resp_format}")


def _construct_file_key(request_id: str, config: StorageConfig) -> str:
    """Constructs file key based on desired naming convention and request id, e.g. 23847234.json"""
    naming = config.details.get(
        StorageDetails.NAMING.value, FileNaming.request_id.value
    )
    if naming != FileNaming.request_id.value:
        raise ValueError(f"File naming of {naming} not supported")
    else:
        return f"{request_id}.{get_extension(config.format)}"


def _get_uploader_from_config_type(storage_type: StorageType) -> Any:
    """Determines which uploader method to use based on storage type"""
    return {
        StorageType.s3.value: _s3_uploader,
        StorageType.onetrust.value: _onetrust_uploader,
        StorageType.local.value: _local_uploader,
    }[storage_type.value]


def _s3_uploader(_: Session, config: StorageConfig, data: Dict, request_id: str) -> str:
    """Constructs necessary info needed for s3 before calling upload"""
    file_key: str = _construct_file_key(request_id, config)

    bucket_name = config.details[StorageDetails.BUCKET.value]
    return upload_to_s3(
        config.secrets, data, bucket_name, file_key, config.format.value
    )


def _onetrust_uploader(
    db: Session, config: StorageConfig, data: Dict, request_id: str
) -> str:

    """Constructs necessary info needed for onetrust before calling upload"""
    request_details: Optional[PrivacyRequest] = PrivacyRequest.get(db, id=request_id)
    if request_details is None:
        raise StorageUploadError(
            f"Request could not be found for request_id: {request_id}"
        )
    payload_data = {
        "language": "en-us",
        "system": config.details[StorageDetails.SERVICE_NAME.value],
        "results": data,
    }
    return upload_to_onetrust(
        payload_data,
        config.secrets,
        request_details.external_id,
    )


def _local_uploader(
    _: Session, config: StorageConfig, data: Dict, request_id: str
) -> str:
    """Uploads data to local storage, used for quick-start/demo purposes"""
    file_key: str = _construct_file_key(request_id, config)
    if not os.path.exists(LOCAL_FIDES_UPLOAD_DIRECTORY):
        os.makedirs(LOCAL_FIDES_UPLOAD_DIRECTORY)
    with open(f"{LOCAL_FIDES_UPLOAD_DIRECTORY}/{file_key}", "w") as f:
        json.dump(data, f, default=_handle_json_encoding)
    return "success"


def _handle_json_encoding(field: Any) -> str:
    """Specify str format for datetime objects"""
    if isinstance(field, datetime):
        return field.strftime("%Y-%m-%dT%H:%M:%S")
    return field
