"""
RCA Engine Module
Root Cause Analysis with multi-factor confidence scoring
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def run_rca_analysis(
    error_log: Dict[str, Any],
    similar_incidents: List[Dict[str, Any]],
    metrics_analysis: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Run root cause analysis with transparent confidence scoring

    Args:
        error_log: Parsed error log
        similar_incidents: List of similar historical incidents from RAG
        metrics_analysis: Metrics anomaly analysis

    Returns:
        RCA result with confidence breakdown
    """
    if not similar_incidents or len(similar_incidents) == 0:
        # No similar incidents found - return low confidence result
        return generate_unknown_result(error_log, metrics_analysis)

    # Get top matching incident
    top_incident = similar_incidents[0]

    # Extract base information
    probable_root_cause = top_incident.get('root_cause', 'Unknown root cause')
    recommended_actions = top_incident.get('recommended_actions', [
        "Investigate error logs",
        "Check service health metrics",
        "Review recent deployments"
    ])
    similar_incident_ids = [inc.get('incident_id', 'unknown') for inc in similar_incidents]

    # Get raw similarity score
    raw_similarity = top_incident.get('similarity_score', 0.0)

    # Calculate confidence boosts
    boost_applied, boost_reasons = calculate_confidence_boost(
        root_cause=probable_root_cause,
        metrics_analysis=metrics_analysis,
        similar_incidents=similar_incidents
    )

    # Calculate final confidence score
    final_score = min(raw_similarity + boost_applied, 0.99)

    # Determine trust level
    trust_level = classify_trust_level(final_score)

    # Generate recommendation text
    recommendation = generate_recommendation(
        trust_level=trust_level,
        root_cause=probable_root_cause
    )

    # Generate explanation
    why_this_score = generate_score_explanation(
        raw_similarity=raw_similarity,
        boost_applied=boost_applied
    )

    # Build result
    result = {
        "confidence": {
            "raw_similarity": round(raw_similarity, 2),
            "boost_applied": round(boost_applied, 2),
            "boost_reasons": boost_reasons,
            "final_score": round(final_score, 2),
            "trust_level": trust_level
        },
        "probable_root_cause": probable_root_cause,
        "recommendation": recommendation,
        "why_this_score": why_this_score,
        "recommended_actions": recommended_actions,
        "similar_incidents": similar_incident_ids,
        "status": "success"
    }

    return result


def calculate_confidence_boost(
    root_cause: str,
    metrics_analysis: Dict[str, Any],
    similar_incidents: List[Dict[str, Any]]
) -> tuple[float, List[str]]:
    """
    Calculate confidence boost based on metric alignment and other factors

    Args:
        root_cause: Diagnosed root cause text
        metrics_analysis: Metrics analysis result
        similar_incidents: List of similar incidents

    Returns:
        Tuple of (total_boost, list_of_reasons)
    """
    total_boost = 0.0
    reasons = []

    root_cause_lower = root_cause.lower()

    # Check metric alignments
    if metrics_analysis.get('has_anomalies', False):
        anomalies = metrics_analysis.get('anomalies', {})

        # CPU alignment
        if 'cpu_utilization' in anomalies:
            if any(keyword in root_cause_lower for keyword in ['cpu', 'processor', 'computation', 'load']):
                total_boost += 0.15
                reasons.append("CPU metric anomaly matches root cause (+0.15)")

        # Memory alignment
        if 'memory_utilization' in anomalies:
            if any(keyword in root_cause_lower for keyword in ['memory', 'heap', 'oom', 'leak', 'garbage']):
                total_boost += 0.15
                reasons.append("Memory metric anomaly matches root cause (+0.15)")

        # Latency alignment
        if 'latency_ms' in anomalies:
            if any(keyword in root_cause_lower for keyword in ['timeout', 'latency', 'slow', 'delay', 'performance']):
                total_boost += 0.15
                reasons.append("Latency metric anomaly matches root cause (+0.15)")

        # Error rate alignment
        if 'error_rate' in anomalies:
            if any(keyword in root_cause_lower for keyword in ['error', 'failure', 'exception', 'crash', 'fail']):
                total_boost += 0.15
                reasons.append("Error rate metric anomaly matches root cause (+0.15)")

        # High severity incident (multiple anomalies)
        if metrics_analysis.get('is_incident', False):
            total_boost += 0.10
            reasons.append("High severity incident detected (+0.10)")

    # Multiple similar incidents boost confidence
    if len(similar_incidents) >= 3:
        # Check if top 3 have similar root causes
        root_causes = [inc.get('root_cause', '') for inc in similar_incidents[:3]]
        if are_root_causes_similar(root_causes):
            total_boost += 0.05
            reasons.append("Multiple similar incidents found (+0.05)")

    # Cap total boost at 0.70
    total_boost = min(total_boost, 0.70)

    return total_boost, reasons


def are_root_causes_similar(root_causes: List[str]) -> bool:
    """
    Check if root causes are similar (basic keyword matching)

    Args:
        root_causes: List of root cause strings

    Returns:
        True if similar
    """
    if len(root_causes) < 2:
        return False

    # Extract keywords from first root cause
    first_keywords = set(root_causes[0].lower().split())

    # Check overlap with other root causes
    for rc in root_causes[1:]:
        keywords = set(rc.lower().split())
        overlap = len(first_keywords & keywords)

        if overlap >= 2:  # At least 2 common keywords
            return True

    return False


def classify_trust_level(confidence_score: float) -> str:
    """
    Classify confidence score into trust level

    Args:
        confidence_score: Final confidence score (0.0 - 1.0)

    Returns:
        Trust level: HIGH, MEDIUM, or LOW
    """
    if confidence_score >= 0.80:
        return "HIGH"
    elif confidence_score >= 0.60:
        return "MEDIUM"
    else:
        return "LOW"


def generate_recommendation(trust_level: str, root_cause: str) -> str:
    """
    Generate recommendation text based on trust level

    Args:
        trust_level: HIGH, MEDIUM, or LOW
        root_cause: Root cause text

    Returns:
        Recommendation string
    """
    if trust_level == "HIGH":
        return f"Confident diagnosis: {root_cause}"
    elif trust_level == "MEDIUM":
        return f"Probable cause (verify manually): {root_cause}"
    else:
        return f"Weak match - manual investigation required: {root_cause}"


def generate_score_explanation(raw_similarity: float, boost_applied: float) -> str:
    """
    Generate human-readable explanation of the score

    Args:
        raw_similarity: Raw similarity score
        boost_applied: Total boost applied

    Returns:
        Explanation string
    """
    # Describe raw similarity
    if raw_similarity >= 0.70:
        similarity_desc = "Strong"
    elif raw_similarity >= 0.50:
        similarity_desc = "Moderate"
    elif raw_similarity >= 0.30:
        similarity_desc = "Weak"
    else:
        similarity_desc = "Very weak"

    explanation = f"{similarity_desc} symptom match ({int(raw_similarity * 100)}%)"

    # Add boost description
    if boost_applied > 0:
        if boost_applied >= 0.20:
            boost_desc = "strong"
        elif boost_applied >= 0.10:
            boost_desc = "moderate"
        else:
            boost_desc = "some"

        explanation += f" + {boost_desc} metric evidence (+{int(boost_applied * 100)}%)"

    return explanation


def generate_unknown_result(
    error_log: Dict[str, Any],
    metrics_analysis: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate result when no similar incidents found

    Args:
        error_log: Parsed error log
        metrics_analysis: Metrics analysis

    Returns:
        Low confidence result
    """
    # Try to infer root cause from error type and metrics
    error_type = error_log.get('error_type', 'Unknown')
    error_message = error_log.get('error_message', '')

    # Basic inference
    inferred_cause = infer_root_cause_from_error(error_type, error_message, metrics_analysis)

    return {
        "confidence": {
            "raw_similarity": 0.0,
            "boost_applied": 0.0,
            "boost_reasons": [],
            "final_score": 0.20,
            "trust_level": "LOW"
        },
        "probable_root_cause": inferred_cause,
        "recommendation": f"No similar historical incidents found. Manual investigation required: {inferred_cause}",
        "why_this_score": "No historical match - inferred from error pattern only",
        "recommended_actions": [
            "Investigate error logs in detail",
            "Check service health and metrics",
            "Review recent code changes and deployments",
            "Consult service documentation",
            "Escalate to on-call engineer if critical"
        ],
        "similar_incidents": [],
        "status": "success"
    }


def infer_root_cause_from_error(
    error_type: str,
    error_message: str,
    metrics_analysis: Dict[str, Any]
) -> str:
    """
    Infer root cause from error pattern and metrics

    Args:
        error_type: Type of error
        error_message: Error message
        metrics_analysis: Metrics analysis

    Returns:
        Inferred root cause
    """
    error_lower = error_message.lower()
    error_type_lower = error_type.lower()

    # Timeout errors
    if 'timeout' in error_type_lower or 'timeout' in error_lower:
        if metrics_analysis.get('has_anomalies', False):
            if 'latency_ms' in metrics_analysis.get('anomalies', {}):
                return "Service timeout likely due to performance degradation (high latency detected)"
        return "Service timeout - possible network issue or downstream dependency failure"

    # Connection errors
    if 'connection' in error_type_lower or 'connection' in error_lower:
        if 'database' in error_lower:
            return "Database connection issue - possible connection pool exhaustion or database unavailability"
        return "Connection error - possible network issue or service unavailability"

    # Memory errors
    if 'memory' in error_type_lower or 'oom' in error_lower:
        return "Memory issue - possible memory leak or insufficient memory allocation"

    # Authentication/Authorization
    if 'auth' in error_type_lower or 'unauthorized' in error_lower:
        return "Authentication/authorization failure - possible token expiration or invalid credentials"

    # Database errors
    if 'database' in error_lower or 'sql' in error_lower:
        return "Database error - possible query issue, deadlock, or database unavailability"

    # Generic based on metrics
    if metrics_analysis.get('has_anomalies', False):
        anomalies = metrics_analysis.get('anomalies', {})
        if 'cpu_utilization' in anomalies and 'memory_utilization' in anomalies:
            return f"{error_type} with high resource usage (CPU and memory) - possible resource exhaustion"
        elif 'cpu_utilization' in anomalies:
            return f"{error_type} with high CPU usage - possible computation-heavy operation or infinite loop"
        elif 'memory_utilization' in anomalies:
            return f"{error_type} with high memory usage - possible memory leak"

    # Fallback
    return f"Unclassified error: {error_type}"


def enhance_recommended_actions(
    recommended_actions: List[str],
    metrics_analysis: Dict[str, Any],
    trust_level: str
) -> List[str]:
    """
    Enhance recommended actions based on context

    Args:
        recommended_actions: Base recommended actions
        metrics_analysis: Metrics analysis
        trust_level: Confidence trust level

    Returns:
        Enhanced list of actions
    """
    enhanced = recommended_actions.copy()

    # Add metric-specific actions
    if metrics_analysis.get('has_anomalies', False):
        anomalies = metrics_analysis.get('anomalies', {})

        if 'memory_utilization' in anomalies:
            enhanced.insert(0, "Check for memory leaks and heap dumps")

        if 'cpu_utilization' in anomalies:
            enhanced.insert(0, "Profile CPU usage and check for infinite loops")

        if 'latency_ms' in anomalies:
            enhanced.insert(0, "Investigate slow queries and downstream dependencies")

    # Add trust-level specific actions
    if trust_level == "LOW":
        enhanced.append("Consult with domain experts")
        enhanced.append("Create new incident documentation if resolved")

    return enhanced[:5]  # Limit to top 5 actions


# Example result:
# {
#   "confidence": {
#     "raw_similarity": 0.44,
#     "boost_applied": 0.25,
#     "boost_reasons": [
#       "Latency metric anomaly matches root cause (+0.15)",
#       "High severity incident detected (+0.10)"
#     ],
#     "final_score": 0.69,
#     "trust_level": "MEDIUM"
#   },
#   "probable_root_cause": "Downstream PaymentService timeout causing order processing failures",
#   "recommendation": "Probable cause (verify manually): Downstream PaymentService timeout",
#   "why_this_score": "Moderate symptom match (44%) + strong metric evidence (+25%)",
#   "recommended_actions": [
#     "Check payment gateway connectivity",
#     "Increase connection pool size",
#     "Review timeout configurations"
#   ],
#   "similar_incidents": ["INC-0001", "INC-0002", "INC-0010"],
#   "status": "success"
# }
