#!/usr/bin/env python3
"""Download Project Gutenberg books and publish them in a public S3 bucket."""

import json
import logging
import os
import sys
import time
from urllib.parse import urlparse

import boto3
import requests
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Share one authenticated client across all S3 operations.
s3 = boto3.client("s3", region_name="us-east-1")


def parse_args() -> tuple[str, str, str]:
    """Return the book-list path, index-page path, and bucket name."""
    if len(sys.argv) < 4:
        log.error(
            "Usage: %s BOOK_LIST INDEX_PAGE BUCKET_NAME",
            os.path.basename(sys.argv[0]),
        )
        sys.exit(1)

    return sys.argv[1], sys.argv[2], sys.argv[3]


def download_books(list_file: str, dest_dir: str) -> list[str]:
    """Download listed books into dest_dir and return their local paths."""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with open(list_file, encoding="utf-8") as file:
            urls = [line.strip() for line in file if line.strip()]
    except OSError as error:
        log.error("Error reading book list %s: %s", list_file, error)
        return []

    book_paths: list[str] = []
    for url in urls:
        filename = os.path.basename(urlparse(url).path)
        if not filename:
            log.error("Could not determine a file name from URL: %s", url)
            continue

        path = os.path.join(dest_dir, filename)
        if os.path.exists(path):
            log.info("Skipping existing book: %s", path)
            book_paths.append(path)
            continue

        try:
            log.info("Downloading %s", url)
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            with open(path, "wb") as file:
                file.write(response.content)
            book_paths.append(path)
        except (requests.RequestException, OSError) as error:
            log.error("Error downloading %s: %s", url, error)
        finally:
            # Be considerate of Project Gutenberg when downloading many books.
            time.sleep(1)

    return book_paths


def create_bucket(bucket: str) -> bool:
    """Create bucket in us-east-1 unless it already exists for this account."""
    try:
        s3.head_bucket(Bucket=bucket)
        log.info("Bucket already exists: %s", bucket)
        return True
    except ClientError:
        log.info("Bucket does not exist yet; creating: %s", bucket)

    try:
        # us-east-1 requires omitting CreateBucketConfiguration.
        s3.create_bucket(Bucket=bucket)
        log.info("Created bucket: %s", bucket)
        return True
    except ClientError as error:
        log.error("Error creating bucket %s: %s", bucket, error)
        return False


def make_public(bucket: str) -> bool:
    """Allow public reads by disabling the block and attaching a policy."""
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
            }
        ],
    }

    try:
        # The public-access block must be changed before S3 accepts the policy.
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info("Made bucket publicly readable: %s", bucket)
        return True
    except ClientError as error:
        log.error("Error making bucket %s public: %s", bucket, error)
        return False


def upload_files(bucket: str, file_paths: list[str]) -> int:
    """Upload plain-text files and return the number uploaded successfully."""
    uploaded = 0
    for path in file_paths:
        key = os.path.basename(path)
        try:
            with open(path, "rb") as file:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=file,
                    ContentType="text/plain; charset=utf-8",
                )
            uploaded += 1
            log.info("Uploaded %s to s3://%s/%s", path, bucket, key)
        except (OSError, ClientError) as error:
            log.error("Error uploading %s: %s", path, error)

    return uploaded


def upload_index(bucket: str, index_path: str) -> bool:
    """Upload index_path as an HTML page named index.html."""
    try:
        with open(index_path, "rb") as file:
            s3.put_object(
                Bucket=bucket,
                Key="index.html",
                Body=file,
                ContentType="text/html",
            )
        log.info("Uploaded %s to s3://%s/index.html", index_path, bucket)
        return True
    except FileNotFoundError:
        log.error("Index file not found: %s", index_path)
    except (OSError, ClientError) as error:
        log.error("Error uploading index page: %s", error)

    return False


def main() -> None:
    """Download the corpus, prepare the bucket, and upload every object."""
    list_file, index_path, bucket = parse_args()
    public_url = f"https://{bucket}.s3.amazonaws.com/index.html"

    book_paths = download_books(list_file, "books")
    if not book_paths:
        log.error("No books are available to upload")
        sys.exit(1)

    if not create_bucket(bucket) or not make_public(bucket):
        log.error("Failed to prepare the public bucket")
        sys.exit(1)

    uploaded = upload_files(bucket, book_paths)
    index_uploaded = upload_index(bucket, index_path)
    log.info("Public index URL: %s", public_url)

    if uploaded != len(book_paths) or not index_uploaded:
        log.error(
            "Upload incomplete: %d of %d books and index=%s",
            uploaded,
            len(book_paths),
            index_uploaded,
        )
        sys.exit(1)

    log.info("Success: uploaded %d books and index.html", uploaded)


if __name__ == "__main__":
    main()
