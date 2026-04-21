"""
DynamoDB Writer Module
Writes RCA analysis results to DynamoDB
"""

import logging
from typing import List, Dict, Any
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

logger = logging.getLogger(__name__)
dynamodb = boto3.resource('dynamodb')


def write_to_dynamodb(result: Dict[str, Any], table_name: str) -> bool:
    """
    Write single analysis result to DynamoDB

    Args:
        result: Analysis result dictionary
        table_name: DynamoDB table name

    Returns:
        True if successful
    """
    try:
        table = dynamodb.Table(table_name)

        # Convert floats to Decimal for DynamoDB
        item = convert_floats_to_decimal(result)

        # Write to DynamoDB
        table.put_item(Item=item)

        logger.debug(f"Written log_id={result['log_id']} to DynamoDB")
        return True

    except ClientError as e:
        logger.error(f"Error writing to DynamoDB: {e.response['Error']['Message']}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error writing to DynamoDB: {str(e)}")
        return False


def batch_write_to_dynamodb(results: List[Dict[str, Any]], table_name: str) -> Dict[str, int]:
    """
    Batch write analysis results to DynamoDB

    Args:
        results: List of analysis result dictionaries
        table_name: DynamoDB table name

    Returns:
        Dictionary with success/failure counts
    """
    if not results:
        logger.warning("No results to write to DynamoDB")
        return {'success': 0, 'failed': 0}

    table = dynamodb.Table(table_name)
    success_count = 0
    failed_count = 0

    # DynamoDB batch_write supports max 25 items per batch
    batch_size = 25

    for i in range(0, len(results), batch_size):
        batch = results[i:i + batch_size]

        try:
            with table.batch_writer() as writer:
                for result in batch:
                    try:
                        # Convert floats to Decimal
                        item = convert_floats_to_decimal(result)

                        # Write item
                        writer.put_item(Item=item)
                        success_count += 1

                    except Exception as e:
                        logger.error(f"Error preparing item for DynamoDB: {str(e)}")
                        failed_count += 1
                        continue

            logger.info(f"Batch {i // batch_size + 1}: Wrote {len(batch)} items to DynamoDB")

        except ClientError as e:
            logger.error(f"Batch write error: {e.response['Error']['Message']}")
            failed_count += len(batch)
            continue
        except Exception as e:
            logger.error(f"Unexpected batch write error: {str(e)}")
            failed_count += len(batch)
            continue

    logger.info(f"DynamoDB write complete: {success_count} success, {failed_count} failed")

    return {
        'success': success_count,
        'failed': failed_count
    }


def convert_floats_to_decimal(obj: Any) -> Any:
    """
    Recursively convert float values to Decimal for DynamoDB compatibility

    Args:
        obj: Object to convert (dict, list, or primitive)

    Returns:
        Converted object
    """
    if isinstance(obj, float):
        # Convert float to Decimal
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        # Recursively convert dictionary
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        # Recursively convert list
        return [convert_floats_to_decimal(item) for item in obj]
    else:
        # Return as-is for other types
        return obj


def query_by_date(table_name: str, analysis_date: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Query DynamoDB by analysis_date

    Args:
        table_name: DynamoDB table name
        analysis_date: Date in YYYY-MM-DD format
        limit: Maximum number of items to return

    Returns:
        List of analysis results
    """
    try:
        table = dynamodb.Table(table_name)

        response = table.query(
            KeyConditionExpression='analysis_date = :date',
            ExpressionAttributeValues={
                ':date': analysis_date
            },
            Limit=limit
        )

        items = response.get('Items', [])
        logger.info(f"Retrieved {len(items)} items for date {analysis_date}")

        return items

    except ClientError as e:
        logger.error(f"Query error: {e.response['Error']['Message']}")
        return []
    except Exception as e:
        logger.error(f"Unexpected query error: {str(e)}")
        return []


def query_by_trust_level(
    table_name: str,
    trust_level: str,
    analysis_date: str = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Query DynamoDB by trust_level using GSI

    Args:
        table_name: DynamoDB table name
        trust_level: Trust level (HIGH, MEDIUM, LOW)
        analysis_date: Optional date filter
        limit: Maximum number of items to return

    Returns:
        List of analysis results
    """
    try:
        table = dynamodb.Table(table_name)

        if analysis_date:
            # Query with date filter
            response = table.query(
                IndexName='trust_level-index',
                KeyConditionExpression='trust_level = :level AND analysis_date = :date',
                ExpressionAttributeValues={
                    ':level': trust_level,
                    ':date': analysis_date
                },
                Limit=limit
            )
        else:
            # Query all dates
            response = table.query(
                IndexName='trust_level-index',
                KeyConditionExpression='trust_level = :level',
                ExpressionAttributeValues={
                    ':level': trust_level
                },
                Limit=limit
            )

        items = response.get('Items', [])
        logger.info(f"Retrieved {len(items)} items with trust_level={trust_level}")

        return items

    except ClientError as e:
        logger.error(f"Query error: {e.response['Error']['Message']}")
        return []
    except Exception as e:
        logger.error(f"Unexpected query error: {str(e)}")
        return []


def query_by_service(
    table_name: str,
    service: str,
    analysis_date: str,
    min_confidence: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Query DynamoDB by service and date with confidence filter

    Args:
        table_name: DynamoDB table name
        service: Service name
        analysis_date: Date in YYYY-MM-DD format
        min_confidence: Minimum confidence score

    Returns:
        List of analysis results
    """
    try:
        table = dynamodb.Table(table_name)

        # Query by date first
        response = table.query(
            KeyConditionExpression='analysis_date = :date',
            FilterExpression='service = :svc AND #result.#conf.#score >= :min_conf',
            ExpressionAttributeNames={
                '#result': 'result',
                '#conf': 'confidence',
                '#score': 'final_score'
            },
            ExpressionAttributeValues={
                ':date': analysis_date,
                ':svc': service,
                ':min_conf': Decimal(str(min_confidence))
            }
        )

        items = response.get('Items', [])
        logger.info(f"Retrieved {len(items)} items for service={service}, confidence>={min_confidence}")

        return items

    except ClientError as e:
        logger.error(f"Query error: {e.response['Error']['Message']}")
        return []
    except Exception as e:
        logger.error(f"Unexpected query error: {str(e)}")
        return []


def get_item(table_name: str, analysis_date: str, log_id: str) -> Dict[str, Any]:
    """
    Get specific item from DynamoDB

    Args:
        table_name: DynamoDB table name
        analysis_date: Analysis date
        log_id: Log ID

    Returns:
        Item dictionary or empty dict if not found
    """
    try:
        table = dynamodb.Table(table_name)

        response = table.get_item(
            Key={
                'analysis_date': analysis_date,
                'log_id': log_id
            }
        )

        return response.get('Item', {})

    except ClientError as e:
        logger.error(f"Get item error: {e.response['Error']['Message']}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected get item error: {str(e)}")
        return {}


def delete_old_records(table_name: str, cutoff_date: str) -> int:
    """
    Delete records older than cutoff date (for data retention)

    Args:
        table_name: DynamoDB table name
        cutoff_date: Date in YYYY-MM-DD format (delete records before this)

    Returns:
        Number of records deleted
    """
    try:
        table = dynamodb.Table(table_name)
        deleted_count = 0

        # Scan for old records
        response = table.scan(
            FilterExpression='analysis_date < :cutoff',
            ExpressionAttributeValues={
                ':cutoff': cutoff_date
            },
            ProjectionExpression='analysis_date, log_id'
        )

        items = response.get('Items', [])

        # Delete in batches
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(
                    Key={
                        'analysis_date': item['analysis_date'],
                        'log_id': item['log_id']
                    }
                )
                deleted_count += 1

        logger.info(f"Deleted {deleted_count} records older than {cutoff_date}")
        return deleted_count

    except ClientError as e:
        logger.error(f"Delete error: {e.response['Error']['Message']}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected delete error: {str(e)}")
        return 0


def get_statistics(table_name: str, analysis_date: str) -> Dict[str, Any]:
    """
    Get statistics for a specific date

    Args:
        table_name: DynamoDB table name
        analysis_date: Date in YYYY-MM-DD format

    Returns:
        Statistics dictionary
    """
    try:
        # Query all records for date
        items = query_by_date(table_name, analysis_date, limit=10000)

        if not items:
            return {}

        # Calculate statistics
        trust_level_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        service_counts = {}
        confidence_scores = []

        for item in items:
            # Trust level distribution
            trust_level = item.get('result', {}).get('confidence', {}).get('trust_level', 'LOW')
            trust_level_counts[trust_level] = trust_level_counts.get(trust_level, 0) + 1

            # Service distribution
            service = item.get('service', 'unknown')
            service_counts[service] = service_counts.get(service, 0) + 1

            # Confidence scores
            score = float(item.get('result', {}).get('confidence', {}).get('final_score', 0))
            confidence_scores.append(score)

        # Calculate average confidence
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0

        return {
            'total_logs': len(items),
            'trust_level_distribution': trust_level_counts,
            'service_distribution': service_counts,
            'average_confidence': round(avg_confidence, 3),
            'min_confidence': round(min(confidence_scores), 3) if confidence_scores else 0.0,
            'max_confidence': round(max(confidence_scores), 3) if confidence_scores else 0.0
        }

    except Exception as e:
        logger.error(f"Error calculating statistics: {str(e)}")
        return {}


# Example item structure in DynamoDB:
# {
#   "analysis_date": "2024-01-15",  # Partition key
#   "log_id": "log-1705324335-abc123",  # Sort key
#   "service": "payment-api",
#   "timestamp": "2024-01-15T14:32:15Z",
#   "log_level": "ERROR",
#   "result": {
#     "confidence": {
#       "raw_similarity": Decimal("0.40"),
#       "boost_applied": Decimal("0.25"),
#       "boost_reasons": [
#         "Latency metric anomaly matches root cause (+0.15)",
#         "High severity incident detected (+0.10)"
#       ],
#       "final_score": Decimal("0.65"),
#       "trust_level": "MEDIUM"
#     },
#     "probable_root_cause": "Downstream payment gateway timeout",
#     "recommendation": "Probable cause (verify manually): ...",
#     "recommended_actions": [...],
#     "similar_incidents": ["INC-0001", "INC-0002"]
#   },
#   "status": "success"
# }
