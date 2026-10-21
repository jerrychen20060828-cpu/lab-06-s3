#!/bin/bash

# Stop on errors, unset variables, and failed commands in pipelines.
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 BOOK_URL BUCKET_NAME EXPIRATION_SECONDS" >&2
    exit 1
fi

BOOK_URL="$1"
BUCKET="$2"
EXPIRATION="$3"

if [[ ! "$EXPIRATION" =~ ^[1-9][0-9]*$ ]]; then
    echo "Expiration must be a positive number of seconds." >&2
    exit 1
fi

# Preserve Gutenberg's file name when downloading the selected book.
FILE_NAME="${BOOK_URL##*/}"
if [[ -z "$FILE_NAME" ]]; then
    echo "The book URL must end with a file name." >&2
    exit 1
fi

mkdir -p "books"
BOOK_PATH="books/$FILE_NAME"
curl --fail --location --show-error "$BOOK_URL" --output "$BOOK_PATH"

# Create the private bucket only when it is not already accessible.
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    echo "Bucket already exists: $BUCKET"
else
    aws s3 mb "s3://$BUCKET" --region "us-east-1"
fi

# Keep the default private settings and upload one plain-text object.
aws s3 cp "$BOOK_PATH" "s3://$BUCKET/$FILE_NAME" \
    --content-type "text/plain; charset=utf-8"

# Print a temporary URL without changing the object's private permissions.
aws s3 presign "s3://$BUCKET/$FILE_NAME" \
    --expires-in "$EXPIRATION" \
    --region "us-east-1"
