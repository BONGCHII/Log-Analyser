"""
Log Fetcher Module
Fetches and filters ERROR/WARN logs from S3
"""

import json
import logging
from typing import List, Dict, Any
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
s3_client = boto3.client('s3')


def fetch_and_filter_logs(
    bucket: str,
    date: str,
    log_levels: List[str] = ['ERROR', 'WARN']
) -> List[Dict[str, Any]]:
    """
    Fetch logs from S3 for a specific date and filter by log level

    Args:
        bucket: S3 bucket name
        date: Date in YYYY-MM-DD format
        log_levels: List of log levels to include (default: ['ERROR', 'WARN'])

    Returns:
        List of filtered log dictionaries
    """
    try:
        # S3 key pattern: logs/{date}/{service}/
        # or: {date}/{service}/logs.json
        # Adjust based on your S3 structure
        prefix = f"logs/{date}/"

        logger.info(f"Fetching logs from s3://{bucket}/{prefix}")

        # List all objects with the date prefix
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

        all_logs = []
        file_count = 0

        for page in pages:
            if 'Contents' not in page:
                logger.warning(f"No logs found for prefix: {prefix}")
                continue

            for obj in page['Contents']:
                key = obj['Key']

                # Skip non-log files
                if not (key.endswith('.json') or key.endswith('.log')):
                    continue

                try:
                    # Fetch log file
                    response = s3_client.get_object(Bucket=bucket, Key=key)
                    content = response['Body'].read().decode('utf-8')

                    # Parse logs (handle both JSON and newline-delimited JSON)
                    logs = parse_log_content(content, key)

                    # Filter by log level
                    filtered_logs = [
                        log for log in logs
                        if log.get('level', '').upper() in [level.upper() for level in log_levels]
                    ]

                    all_logs.extend(filtered_logs)
                    file_count += 1

                    logger.debug(f"Processed {key}: {len(filtered_logs)} ERROR/WARN logs")

                except ClientError as e:
                    logger.error(f"Error fetching {key}: {str(e)}")
                    continue
                except Exception as e:
                    logger.error(f"Error parsing {key}: {str(e)}")
                    continue

        logger.info(f"Fetched {len(all_logs)} ERROR/WARN logs from {file_count} files")

        # Add unique log_id if missing
        for i, log in enumerate(all_logs):
            if 'log_id' not in log:
                log['log_id'] = f"log-{int(log.get('timestamp', 0))}-{i}"

        return all_logs

    except Exception as e:
        logger.error(f"Failed to fetch logs from S3: {str(e)}")
        raise


def parse_log_content(content: str, source_key: str) -> List[Dict[str, Any]]:
    """
    Parse log content from various formats

    Args:
        content: Raw log content
        source_key: S3 key for debugging

    Returns:
        List of parsed log dictionaries
    """
    logs = []

    try:
        # Try parsing as single JSON object
        log_data = json.loads(content)

        # If it's an array, return it
        if isinstance(log_data, list):
            return log_data

        # If it's a single object, wrap in array
        if isinstance(log_data, dict):
            return [log_data]

    except json.JSONDecodeError:
        # Try parsing as newline-delimited JSON (NDJSON)
        for line_num, line in enumerate(content.strip().split('\n'), 1):
            if not line.strip():
                continue

            try:
                log_entry = json.loads(line)
                logs.append(log_entry)
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON in {source_key}:{line_num}: {str(e)}")
                continue

    return logs


def extract_service_from_key(s3_key: str) -> str:
    """
    Extract service name from S3 key path

    Args:
        s3_key: S3 object key (e.g., "logs/2024-01-15/payment-api/app.log")

    Returns:
        Service name (e.g., "payment-api")
    """
    parts = s3_key.split('/')

    # Typical structure: logs/{date}/{service}/{filename}
    if len(parts) >= 3:
        return parts[2]

    return "unknown-service"


def enrich_log_metadata(log: Dict[str, Any], s3_key: str) -> Dict[str, Any]:
    """
    Enrich log with metadata if missing

    Args:
        log: Log dictionary
        s3_key: S3 key for extracting context

    Returns:
        Enriched log dictionary
    """
    # Add service if missing
    if 'service' not in log:
        log['service'] = extract_service_from_key(s3_key)

    # Add timestamp if missing
    if 'timestamp' not in log:
        import time
        log['timestamp'] = int(time.time())

    # Normalize level field
    if 'level' not in log:
        if 'severity' in log:
            log['level'] = log['severity']
        elif 'ERROR' in log.get('message', '').upper():
            log['level'] = 'ERROR'
        else:
            log['level'] = 'WARN'

    return log


# Example log format expected:
# {
#   "timestamp": "2024-01-15T14:32:15Z",
#   "level": "ERROR",
#   "service": "payment-api",
#   "message": "Database connection timeout after 30s",
#   "metrics": {
#     "cpu_utilization": 85,
#     "memory_utilization": 78,
#     "error_rate": 0.15,
#     "latency_ms": 650
#   },
#   "stack_trace": "...",
#   "context": {...}
# }
