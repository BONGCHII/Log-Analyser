"""
Knowledge Builder Module
Builds and updates self-learning knowledge base from production logs
"""

import json
import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import boto3
from botocore.exceptions import ClientError
from sentence_transformers import SentenceTransformer
import faiss

logger = logging.getLogger(__name__)
s3_client = boto3.client('s3')

# Global model instance (loaded once per Lambda container)
_model = None


def get_model() -> SentenceTransformer:
    """
    Get or initialize the sentence transformer model
    Lazy loading to avoid cold start delays
    """
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model: all-MiniLM-L6-v2")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Model loaded successfully")
    return _model


def load_knowledge_base(bucket: str, key: str) -> List[Dict[str, Any]]:
    """
    Load existing knowledge base from S3

    Args:
        bucket: S3 bucket name
        key: S3 key path to incidents.json

    Returns:
        List of incident dictionaries
    """
    try:
        logger.info(f"Loading knowledge base from s3://{bucket}/{key}")

        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')

        incidents = json.loads(content)

        if not isinstance(incidents, list):
            logger.error("Knowledge base is not a list, initializing empty")
            return []

        logger.info(f"Loaded {len(incidents)} incidents from knowledge base")
        return incidents

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.warning(f"Knowledge base not found at s3://{bucket}/{key}, starting empty")
            return []
        else:
            logger.error(f"Error loading knowledge base: {str(e)}")
            raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in knowledge base: {str(e)}")
        return []


def save_knowledge_base(incidents: List[Dict[str, Any]], bucket: str, key: str) -> bool:
    """
    Save updated knowledge base to S3

    Args:
        incidents: List of incident dictionaries
        bucket: S3 bucket name
        key: S3 key path

    Returns:
        True if successful
    """
    try:
        logger.info(f"Saving {len(incidents)} incidents to s3://{bucket}/{key}")

        # Convert to JSON
        json_content = json.dumps(incidents, indent=2, ensure_ascii=False)

        # Upload to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json_content.encode('utf-8'),
            ContentType='application/json'
        )

        logger.info("Knowledge base saved successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to save knowledge base: {str(e)}")
        raise


def build_faiss_index(
    incidents: List[Dict[str, Any]]
) -> Tuple[Optional[faiss.IndexFlatIP], Optional[np.ndarray]]:
    """
    Build FAISS index from incidents

    Args:
        incidents: List of incident dictionaries

    Returns:
        Tuple of (FAISS index, embeddings array)
    """
    if len(incidents) == 0:
        logger.warning("No incidents to build FAISS index, returning None")
        return None, None

    try:
        logger.info(f"Building FAISS index for {len(incidents)} incidents")

        model = get_model()

        # Generate embeddings for each incident
        # Combine symptoms and root_cause for better matching
        texts = []
        for incident in incidents:
            symptoms = incident.get('symptoms', '')
            root_cause = incident.get('root_cause', '')
            service = incident.get('service', '')
            text = f"{service} {symptoms} {root_cause}"
            texts.append(text)

        # Encode in batches
        embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

        # Normalize embeddings for cosine similarity (using IndexFlatIP)
        faiss.normalize_L2(embeddings)

        # Create FAISS index
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatIP(dimension)  # Inner Product = cosine similarity after normalization
        index.add(embeddings)

        logger.info(f"FAISS index built successfully (dimension={dimension}, count={index.ntotal})")

        return index, embeddings

    except Exception as e:
        logger.error(f"Failed to build FAISS index: {str(e)}")
        raise


def detect_and_add_new_incidents(
    logs: List[Dict[str, Any]],
    existing_incidents: List[Dict[str, Any]],
    faiss_index: Optional[faiss.IndexFlatIP],
    incident_embeddings: Optional[np.ndarray],
    similarity_threshold: float = 0.85
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Detect new error patterns and add them to knowledge base

    Args:
        logs: List of error logs
        existing_incidents: Current incidents
        faiss_index: FAISS index (None if knowledge base is empty)
        incident_embeddings: Incident embeddings (None if knowledge base is empty)
        similarity_threshold: Threshold for considering pattern as "new"

    Returns:
        Tuple of (new_incidents, updated_knowledge_base)
    """
    model = get_model()
    new_incidents = []
    updated_knowledge_base = existing_incidents.copy()

    # If knowledge base is empty, all logs become incidents
    if faiss_index is None or len(existing_incidents) == 0:
        logger.info("Knowledge base is empty, creating incidents from all logs")

        # Group logs by service and error message to deduplicate
        unique_errors = {}
        for log in logs:
            error_key = f"{log.get('service', 'unknown')}::{log.get('message', '')[:100]}"
            if error_key not in unique_errors:
                unique_errors[error_key] = log

        # Create incidents from unique errors
        for idx, log in enumerate(unique_errors.values(), 1):
            incident = create_incident_from_log(log, incident_id=f"INC-{idx:04d}")
            new_incidents.append(incident)
            updated_knowledge_base.append(incident)

        logger.info(f"Created {len(new_incidents)} incidents from scratch")
        return new_incidents, updated_knowledge_base

    # Knowledge base exists - detect new patterns
    logger.info(f"Detecting new patterns (threshold={similarity_threshold})")

    processed_errors = set()
    new_pattern_count = 0

    for log in logs:
        try:
            # Create unique key for this error pattern
            error_key = f"{log.get('service', '')}::{log.get('message', '')[:100]}"

            # Skip if already processed
            if error_key in processed_errors:
                continue
            processed_errors.add(error_key)

            # Encode log message
            service = log.get('service', '')
            message = log.get('message', '')
            query_text = f"{service} {message}"
            query_embedding = model.encode([query_text], convert_to_numpy=True)
            faiss.normalize_L2(query_embedding)

            # Search for similar incidents
            distances, indices = faiss_index.search(query_embedding, k=1)
            max_similarity = distances[0][0] if len(distances[0]) > 0 else 0.0

            # If similarity below threshold, it's a new pattern
            if max_similarity < similarity_threshold:
                new_pattern_count += 1
                incident_id = f"INC-{len(updated_knowledge_base) + 1:04d}"

                new_incident = create_incident_from_log(log, incident_id)
                new_incidents.append(new_incident)
                updated_knowledge_base.append(new_incident)

                logger.debug(
                    f"New pattern detected: {incident_id} "
                    f"(similarity={max_similarity:.3f}, threshold={similarity_threshold})"
                )

        except Exception as e:
            logger.error(f"Error processing log for pattern detection: {str(e)}")
            continue

    logger.info(f"Detected {len(new_incidents)} new error patterns")
    return new_incidents, updated_knowledge_base


def create_incident_from_log(log: Dict[str, Any], incident_id: str) -> Dict[str, Any]:
    """
    Create incident dictionary from log entry

    Args:
        log: Log dictionary
        incident_id: Unique incident ID

    Returns:
        Incident dictionary
    """
    from datetime import datetime

    incident = {
        "incident_id": incident_id,
        "timestamp": log.get('timestamp', datetime.utcnow().isoformat()),
        "service": log.get('service', 'unknown-service'),
        "symptoms": log.get('message', 'No error message'),
        "root_cause": "Auto-detected from production logs",
        "recommended_actions": [
            "Investigate root cause",
            "Check service metrics and logs",
            "Review recent deployments"
        ]
    }

    # Add stack trace if available
    if 'stack_trace' in log:
        incident['stack_trace'] = log['stack_trace']

    # Add metrics if available
    if 'metrics' in log:
        incident['metrics'] = log['metrics']

    return incident


def compute_similarity(
    query: str,
    incidents: List[Dict[str, Any]],
    model: SentenceTransformer,
    top_k: int = 3
) -> List[Tuple[int, float]]:
    """
    Compute similarity between query and incidents

    Args:
        query: Query text
        incidents: List of incidents
        model: SentenceTransformer model
        top_k: Number of top results to return

    Returns:
        List of (incident_index, similarity_score) tuples
    """
    if len(incidents) == 0:
        return []

    # Encode query
    query_embedding = model.encode([query], convert_to_numpy=True)
    faiss.normalize_L2(query_embedding)

    # Encode incidents
    incident_texts = [
        f"{inc.get('service', '')} {inc.get('symptoms', '')} {inc.get('root_cause', '')}"
        for inc in incidents
    ]
    incident_embeddings = model.encode(incident_texts, convert_to_numpy=True)
    faiss.normalize_L2(incident_embeddings)

    # Compute cosine similarity
    similarities = np.dot(query_embedding, incident_embeddings.T)[0]

    # Get top-k
    top_indices = np.argsort(similarities)[::-1][:top_k]
    results = [(int(idx), float(similarities[idx])) for idx in top_indices]

    return results


# Example incident format in incidents.json:
# {
#   "incident_id": "INC-0001",
#   "timestamp": "2024-01-15T10:23:45Z",
#   "service": "payment-api",
#   "symptoms": "Database connection timeout after 30 seconds",
#   "root_cause": "Database connection pool exhausted due to connection leak",
#   "recommended_actions": [
#     "Restart database connection pool",
#     "Check for connection leaks in code",
#     "Increase connection pool size"
#   ]
# }
