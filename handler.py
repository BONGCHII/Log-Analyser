"""
Lambda handler for AI Root Cause Analyzer
Orchestrates daily batch processing of ERROR/WARN logs from S3
"""

import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any

# Import custom modules
from lambda.log_fetcher import fetch_and_filter_logs
from lambda.knowledge_builder import (
    load_knowledge_base,
    detect_and_add_new_incidents,
    save_knowledge_base,
    build_faiss_index
)
from lambda.log_parser import parse_log_message
from lambda.metrics_analyzer import analyze_metrics
from lambda.rag_pipeline import search_similar_incidents
from lambda.rca_engine import run_rca_analysis
from lambda.dynamodb_writer import write_to_dynamodb, batch_write_to_dynamodb

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
S3_BUCKET = os.environ.get('S3_BUCKET')
KNOWLEDGE_BASE_BUCKET = os.environ.get('KNOWLEDGE_BASE_BUCKET')
KNOWLEDGE_BASE_KEY = os.environ.get('KNOWLEDGE_BASE_KEY', 'knowledge-base/incidents.json')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'rca-analysis')
LOG_LEVEL_FILTER = os.environ.get('LOG_LEVEL_FILTER', 'ERROR,WARN').split(',')
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '100'))
TOP_K_SIMILAR = int(os.environ.get('TOP_K_SIMILAR', '3'))
SIMILARITY_THRESHOLD = float(os.environ.get('SIMILARITY_THRESHOLD', '0.85'))


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler function

    Args:
        event: Lambda event (optional 'date' field for specific date processing)
        context: Lambda context

    Returns:
        Response with analysis summary
    """
    try:
        # Determine date to process (default: yesterday)
        target_date = event.get('date')
        if not target_date:
            yesterday = datetime.utcnow() - timedelta(days=1)
            target_date = yesterday.strftime('%Y-%m-%d')

        logger.info(f"Starting RCA analysis for date: {target_date}")

        # Step 1: Load existing knowledge base
        logger.info("Step 1: Loading existing knowledge base from S3")
        existing_incidents = load_knowledge_base(
            bucket=KNOWLEDGE_BASE_BUCKET,
            key=KNOWLEDGE_BASE_KEY
        )
        logger.info(f"Loaded {len(existing_incidents)} existing incidents")

        # Step 2: Fetch and filter logs from S3
        logger.info(f"Step 2: Fetching ERROR/WARN logs from S3 for {target_date}")
        logs = fetch_and_filter_logs(
            bucket=S3_BUCKET,
            date=target_date,
            log_levels=LOG_LEVEL_FILTER
        )
        logger.info(f"Fetched {len(logs)} ERROR/WARN logs")

        if len(logs) == 0:
            logger.warning(f"No logs found for {target_date}")
            return {
                'statusCode': 200,
                'message': f'No ERROR/WARN logs found for {target_date}',
                'summary': {
                    'total_logs_processed': 0,
                    'new_incidents_added': 0,
                    'knowledge_base_size': len(existing_incidents)
                }
            }

        # Step 3: Build FAISS index from existing incidents
        logger.info("Step 3: Building FAISS index from knowledge base")
        faiss_index, incident_embeddings = build_faiss_index(existing_incidents)

        # Step 4: Detect and add new incidents
        logger.info("Step 4: Detecting new error patterns")
        new_incidents, updated_knowledge_base = detect_and_add_new_incidents(
            logs=logs,
            existing_incidents=existing_incidents,
            faiss_index=faiss_index,
            incident_embeddings=incident_embeddings,
            similarity_threshold=SIMILARITY_THRESHOLD
        )
        logger.info(f"Detected {len(new_incidents)} new error patterns")

        # Step 5: Save updated knowledge base to S3
        if len(new_incidents) > 0:
            logger.info("Step 5: Saving updated knowledge base to S3")
            save_knowledge_base(
                incidents=updated_knowledge_base,
                bucket=KNOWLEDGE_BASE_BUCKET,
                key=KNOWLEDGE_BASE_KEY
            )
            logger.info("Knowledge base updated successfully")

            # Rebuild FAISS index with new incidents
            faiss_index, incident_embeddings = build_faiss_index(updated_knowledge_base)
        else:
            logger.info("Step 5: No new incidents to add, skipping knowledge base update")

        # Step 6: Process logs in batches for RCA
        logger.info(f"Step 6: Processing {len(logs)} logs in batches of {BATCH_SIZE}")
        analysis_results = []
        confidence_distribution = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        bottleneck_counter = defaultdict(list)

        for i in range(0, len(logs), BATCH_SIZE):
            batch = logs[i:i + BATCH_SIZE]
            logger.info(f"Processing batch {i // BATCH_SIZE + 1}/{(len(logs) + BATCH_SIZE - 1) // BATCH_SIZE}")

            for log in batch:
                try:
                    # Parse log message
                    parsed_log = parse_log_message(log)

                    # Analyze metrics (if available)
                    metrics_analysis = analyze_metrics(log.get('metrics', {}))

                    # Search for similar incidents using RAG
                    similar_incidents = search_similar_incidents(
                        query=parsed_log['error_message'],
                        service=log['service'],
                        metrics_context=metrics_analysis,
                        faiss_index=faiss_index,
                        incidents=updated_knowledge_base,
                        top_k=TOP_K_SIMILAR
                    )

                    # Run RCA analysis
                    rca_result = run_rca_analysis(
                        error_log=parsed_log,
                        similar_incidents=similar_incidents,
                        metrics_analysis=metrics_analysis
                    )

                    # Build complete result
                    result = {
                        'analysis_date': target_date,
                        'log_id': log.get('log_id', f"log-{int(datetime.utcnow().timestamp())}-{i}"),
                        'service': log['service'],
                        'timestamp': log.get('timestamp', datetime.utcnow().isoformat()),
                        'log_level': log.get('level', 'ERROR'),
                        'result': rca_result,
                        'status': 'success'
                    }

                    analysis_results.append(result)

                    # Track confidence distribution
                    trust_level = rca_result['confidence']['trust_level']
                    confidence_distribution[trust_level] += 1

                    # Track bottlenecks
                    if trust_level in ['HIGH', 'MEDIUM']:
                        bottleneck_key = f"{log['service']}: {rca_result['probable_root_cause'][:80]}"
                        bottleneck_counter[bottleneck_key].append(result)

                except Exception as e:
                    logger.error(f"Error processing log {log.get('log_id', 'unknown')}: {str(e)}")
                    continue

        logger.info(f"Processed {len(analysis_results)} logs successfully")

        # Step 7: Write results to DynamoDB
        logger.info("Step 7: Writing results to DynamoDB")
        batch_write_to_dynamodb(
            results=analysis_results,
            table_name=DYNAMODB_TABLE
        )
        logger.info("Results written to DynamoDB successfully")

        # Step 8: Generate top bottlenecks
        top_bottlenecks = []
        for bottleneck, occurrences in sorted(
            bottleneck_counter.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )[:10]:
            top_bottlenecks.append(f"{bottleneck} ({len(occurrences)} occurrences)")

        # Build response
        response = {
            'statusCode': 200,
            'message': f"Analyzed {len(analysis_results)} ERROR/WARN logs from {target_date}",
            'summary': {
                'total_logs_processed': len(analysis_results),
                'new_incidents_added': len(new_incidents),
                'knowledge_base_size': len(updated_knowledge_base),
                'high_confidence': confidence_distribution['HIGH'],
                'medium_confidence': confidence_distribution['MEDIUM'],
                'low_confidence': confidence_distribution['LOW'],
                'top_bottlenecks': top_bottlenecks
            }
        }

        logger.info(f"Analysis complete: {json.dumps(response['summary'])}")
        return response

    except Exception as e:
        logger.error(f"Lambda handler failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e),
            'message': 'RCA analysis failed'
        }


def get_yesterday_date() -> str:
    """Helper function to get yesterday's date in YYYY-MM-DD format"""
    yesterday = datetime.utcnow() - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d')


if __name__ == "__main__":
    # For local testing
    test_event = {
        'date': '2024-01-15'
    }

    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
