"""Storage abstraction for S3/MinIO data lake operations."""

import io
from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import structlog
from botocore.exceptions import ClientError, NoCredentialsError

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BUCKET = "lakay-data-lake"
DEFAULT_ENDPOINT = "http://localhost:9000"
DEFAULT_ACCESS_KEY = "minioadmin"
DEFAULT_SECRET_KEY = "minioadmin"


def _get_s3_client(
    endpoint_url: str = DEFAULT_ENDPOINT,
    access_key: str = DEFAULT_ACCESS_KEY,
    secret_key: str = DEFAULT_SECRET_KEY,
):
    """Create a boto3 S3 client for MinIO."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )


class DataLakeStorage:
    """Abstraction over S3/MinIO for data lake read/write operations."""

    def __init__(
        self,
        bucket: str = DEFAULT_BUCKET,
        endpoint_url: str = DEFAULT_ENDPOINT,
        access_key: str = DEFAULT_ACCESS_KEY,
        secret_key: str = DEFAULT_SECRET_KEY,
    ):
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _get_s3_client(self.endpoint_url, self.access_key, self.secret_key)
        return self._client

    def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
            logger.info("bucket_created", bucket=self.bucket)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_batch(
        self,
        table: pa.Table,
        layer: str,
        event_type: str,
        dt: datetime,
        batch_id: str = "batch001",
    ) -> tuple[str, int]:
        """Write a PyArrow table as a Parquet file to the data lake.

        Returns (object_key, size_bytes).
        """
        if layer == "bronze":
            key = (
                f"{layer}/{event_type}/{dt.year}/{dt.month:02d}/{dt.day:02d}"
                f"/{dt.hour:02d}/events_{int(dt.timestamp())}_{batch_id}.parquet"
            )
        elif layer == "silver":
            key = (
                f"{layer}/{event_type}/{dt.year}/{dt.month:02d}/{dt.day:02d}"
                f"/events_{int(dt.timestamp())}_{batch_id}.parquet"
            )
        else:
            # gold or other layers use dataset_name instead of event_type
            key = (
                f"{layer}/{event_type}/{dt.year}/{dt.month:02d}/{dt.day:02d}"
                f"/data_{int(dt.timestamp())}_{batch_id}.parquet"
            )

        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        data = buf.getvalue()
        size_bytes = len(data)

        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="application/octet-stream",
        )
        logger.info(
            "parquet_written",
            layer=layer,
            key=key,
            record_count=table.num_rows,
            size_bytes=size_bytes,
        )
        return key, size_bytes

    def write_key(self, key: str, data: bytes) -> int:
        """Write raw bytes to a specific key. Returns size_bytes."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="application/octet-stream",
        )
        return len(data)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_partition(self, key: str) -> pa.Table:
        """Read a Parquet file from the data lake and return a PyArrow table."""
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        data = resp["Body"].read()
        buf = io.BytesIO(data)
        return pq.read_table(buf)

    # ------------------------------------------------------------------
    # List / Stats
    # ------------------------------------------------------------------

    def list_partitions(
        self,
        layer: str,
        event_type: str | None = None,
        prefix: str | None = None,
    ) -> list[dict]:
        """List partition objects under a layer with optional filters.

        Returns a list of dicts: {key, size_bytes, last_modified}.
        """
        search_prefix = prefix or layer + "/"
        if event_type and not prefix:
            search_prefix = f"{layer}/{event_type}/"

        results: list[dict] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=search_prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".parquet"):
                    results.append(
                        {
                            "key": obj["Key"],
                            "size_bytes": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat()
                            if hasattr(obj["LastModified"], "isoformat")
                            else str(obj["LastModified"]),
                        }
                    )
        return results

    def get_partition_stats(self, layer: str) -> dict:
        """Aggregate stats for a layer: file count, total size."""
        partitions = self.list_partitions(layer)
        total_size = sum(p["size_bytes"] for p in partitions)
        return {
            "layer": layer,
            "partition_count": len(partitions),
            "total_size_bytes": total_size,
        }

    def key_exists(self, key: str) -> bool:
        """Check if a key exists in the bucket."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except (ClientError, NoCredentialsError):
            return False
