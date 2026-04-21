"""
RAG Pipeline Module
Retrieves similar incidents using FAISS vector search
"""

import logging
import numpy as np
from typing import List, Dict, Any, Optional
import faiss
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Global model instance (reused across invocations)
_model = None


def get_model() -> SentenceTransformer:
    """
    Get or initialize the sentence transformer model
    """
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model


def search_similar_incidents(
    query: str,
    service: str,
    metrics_context: Dict[str, Any],
    faiss_index: Optional[faiss.IndexFlatIP],
    incidents: List[Dict[str, Any]],
    top_k: int = 3
) -> List[Dict[str, Any]]:
    """
    Search for similar incidents using RAG

    Args:
        query: Error message query
        service: Service name
        metrics_context: Metrics analysis result
        faiss_index: FAISS index
        incidents: List of incidents
        top_k: Number of results to return

    Returns:
        List of similar incidents with similarity scores
    """
    if faiss_index is None or len(incidents) == 0:
        logger.warning("No FAISS index or incidents available")
        return []

    try:
        # Enhance query with service and metrics context
        enhanced_query = enhance_query(query, service, metrics_context)

        logger.debug(f"Enhanced query: {enhanced_query}")

        # Generate query embedding
        model = get_model()
        query_embedding = model.encode([enhanced_query], convert_to_numpy=True)

        # Normalize for cosine similarity
        faiss.normalize_L2(query_embedding)

        # Search FAISS index
        distances, indices = faiss_index.search(query_embedding, k=top_k)

        # Build results
        results = []
        for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
            if idx == -1:  # Invalid index
                continue

            incident = incidents[idx].copy()
            incident['similarity_score'] = float(distance)
            incident['rank'] = i + 1

            results.append(incident)

        logger.info(f"Found {len(results)} similar incidents (top-{top_k})")

        return results

    except Exception as e:
        logger.error(f"Error in similarity search: {str(e)}")
        return []


def enhance_query(
    query: str,
    service: str,
    metrics_context: Dict[str, Any]
) -> str:
    """
    Enhance query with service name and metrics context

    Args:
        query: Original error message
        service: Service name
        metrics_context: Metrics analysis result

    Returns:
        Enhanced query string
    """
    components = [service, query]

    # Add metric context if anomalies detected
    if metrics_context.get('has_anomalies', False):
        anomalies = metrics_context.get('anomalies', {})

        for metric_name, anomaly in anomalies.items():
            description = anomaly.get('description', '')

            if metric_name == 'cpu_utilization':
                components.append(f"high CPU {anomaly['value']}%")
            elif metric_name == 'memory_utilization':
                components.append(f"high memory {anomaly['value']}%")
            elif metric_name == 'error_rate':
                components.append(f"error rate {anomaly['value']:.1%}")
            elif metric_name == 'latency_ms':
                components.append(f"latency {anomaly['value']}ms")

    return " ".join(components)


def rerank_results(
    results: List[Dict[str, Any]],
    service: str,
    metrics_context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Re-rank results based on additional factors

    Args:
        results: Initial similarity search results
        service: Service name
        metrics_context: Metrics analysis result

    Returns:
        Re-ranked results
    """
    if not results:
        return results

    for result in results:
        boost = 0.0

        # Boost if service matches exactly
        if result.get('service', '') == service:
            boost += 0.05

        # Boost if metrics align with root cause
        if metrics_context.get('has_anomalies', False):
            root_cause = result.get('root_cause', '').lower()

            for metric_name in metrics_context.get('anomalies', {}):
                if metric_name == 'cpu_utilization' and 'cpu' in root_cause:
                    boost += 0.03
                elif metric_name == 'memory_utilization' and 'memory' in root_cause:
                    boost += 0.03
                elif metric_name == 'latency_ms' and ('timeout' in root_cause or 'latency' in root_cause):
                    boost += 0.03
                elif metric_name == 'error_rate' and 'error' in root_cause:
                    boost += 0.03

        # Apply boost to similarity score
        result['original_similarity'] = result['similarity_score']
        result['similarity_score'] = min(result['similarity_score'] + boost, 0.99)

    # Sort by adjusted similarity score
    results.sort(key=lambda x: x['similarity_score'], reverse=True)

    return results


def filter_by_service(
    results: List[Dict[str, Any]],
    service: str,
    min_similarity: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Filter results by service and minimum similarity

    Args:
        results: Search results
        service: Target service name
        min_similarity: Minimum similarity threshold

    Returns:
        Filtered results
    """
    filtered = []

    for result in results:
        # Skip if similarity too low
        if result.get('similarity_score', 0) < min_similarity:
            continue

        # Prefer same service, but include others if similarity is high
        result_service = result.get('service', '')

        if result_service == service:
            filtered.append(result)
        elif result.get('similarity_score', 0) >= 0.7:
            # Include cross-service matches if highly similar
            filtered.append(result)

    return filtered


def get_diverse_results(
    results: List[Dict[str, Any]],
    diversity_threshold: float = 0.85
) -> List[Dict[str, Any]]:
    """
    Get diverse results by filtering out near-duplicates

    Args:
        results: Search results
        diversity_threshold: Similarity threshold for considering items as duplicates

    Returns:
        Diverse results
    """
    if len(results) <= 1:
        return results

    diverse = [results[0]]  # Always include top result

    model = get_model()

    # Get embeddings for selected results
    selected_texts = [
        f"{r.get('service', '')} {r.get('symptoms', '')} {r.get('root_cause', '')}"
        for r in diverse
    ]
    selected_embeddings = model.encode(selected_texts, convert_to_numpy=True)
    faiss.normalize_L2(selected_embeddings)

    # Check remaining results
    for result in results[1:]:
        # Get embedding for candidate
        candidate_text = f"{result.get('service', '')} {result.get('symptoms', '')} {result.get('root_cause', '')}"
        candidate_embedding = model.encode([candidate_text], convert_to_numpy=True)
        faiss.normalize_L2(candidate_embedding)

        # Compute similarity with already selected results
        similarities = np.dot(candidate_embedding, selected_embeddings.T)[0]
        max_similarity = np.max(similarities)

        # Include if sufficiently different
        if max_similarity < diversity_threshold:
            diverse.append(result)
            selected_texts.append(candidate_text)
            selected_embeddings = np.vstack([selected_embeddings, candidate_embedding])

    logger.debug(f"Filtered to {len(diverse)} diverse results from {len(results)}")

    return diverse


def explain_similarity(
    query: str,
    incident: Dict[str, Any],
    similarity_score: float
) -> str:
    """
    Generate human-readable explanation of why this incident is similar

    Args:
        query: Original query
        incident: Matched incident
        similarity_score: Similarity score

    Returns:
        Explanation string
    """
    explanations = []

    # Check for keyword matches
    query_lower = query.lower()
    symptoms = incident.get('symptoms', '').lower()
    root_cause = incident.get('root_cause', '').lower()

    # Error type matches
    if 'timeout' in query_lower and 'timeout' in symptoms:
        explanations.append("timeout pattern match")
    if 'connection' in query_lower and 'connection' in symptoms:
        explanations.append("connection issue match")
    if 'memory' in query_lower and 'memory' in root_cause:
        explanations.append("memory-related issue")
    if 'database' in query_lower and 'database' in symptoms:
        explanations.append("database issue match")

    # Service match
    if 'service' in incident:
        explanations.append(f"from {incident['service']}")

    # Similarity score description
    if similarity_score >= 0.8:
        confidence = "very high"
    elif similarity_score >= 0.6:
        confidence = "high"
    elif similarity_score >= 0.4:
        confidence = "moderate"
    else:
        confidence = "low"

    explanation = f"{confidence} similarity ({similarity_score:.2f})"
    if explanations:
        explanation += f": {', '.join(explanations)}"

    return explanation


def compute_aggregate_confidence(results: List[Dict[str, Any]]) -> float:
    """
    Compute aggregate confidence from multiple similar incidents

    Args:
        results: List of similar incidents

    Returns:
        Aggregate confidence score
    """
    if not results:
        return 0.0

    # Weight by rank (top result has more influence)
    weights = [1.0, 0.7, 0.5]  # For top-3
    weighted_sum = 0.0
    weight_total = 0.0

    for i, result in enumerate(results[:3]):
        weight = weights[i] if i < len(weights) else 0.3
        weighted_sum += result.get('similarity_score', 0) * weight
        weight_total += weight

    aggregate = weighted_sum / weight_total if weight_total > 0 else 0.0

    return round(aggregate, 3)


# Example usage:
# results = search_similar_incidents(
#     query="Database connection timeout after 30 seconds",
#     service="payment-api",
#     metrics_context={
#         "has_anomalies": True,
#         "anomalies": {
#             "latency_ms": {"value": 650, "severity": 1}
#         }
#     },
#     faiss_index=index,
#     incidents=incidents,
#     top_k=3
# )

# Example output:
# [
#   {
#     "incident_id": "INC-0042",
#     "service": "payment-api",
#     "symptoms": "Database connection pool exhausted, timeout after 30s",
#     "root_cause": "Connection leak in payment processing code",
#     "recommended_actions": [...],
#     "similarity_score": 0.87,
#     "rank": 1
#   },
#   ...
# ]
