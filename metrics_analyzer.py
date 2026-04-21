"""
Metrics Analyzer Module
Analyzes metrics to detect anomalies and compute severity scores
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def analyze_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze metrics to detect anomalies

    Args:
        metrics: Dictionary of metric values

    Returns:
        Analysis results with anomaly detection
    """
    if not metrics:
        return {
            'has_anomalies': False,
            'anomalies': {},
            'severity_score': 0,
            'is_incident': False
        }

    anomalies = {}
    severity_score = 0

    # Analyze CPU utilization
    if 'cpu_utilization' in metrics:
        cpu = metrics['cpu_utilization']
        cpu_analysis = analyze_cpu(cpu)
        if cpu_analysis['is_anomalous']:
            anomalies['cpu_utilization'] = cpu_analysis
            severity_score += cpu_analysis['severity']

    # Analyze memory utilization
    if 'memory_utilization' in metrics:
        memory = metrics['memory_utilization']
        memory_analysis = analyze_memory(memory)
        if memory_analysis['is_anomalous']:
            anomalies['memory_utilization'] = memory_analysis
            severity_score += memory_analysis['severity']

    # Analyze error rate
    if 'error_rate' in metrics:
        error_rate = metrics['error_rate']
        error_analysis = analyze_error_rate(error_rate)
        if error_analysis['is_anomalous']:
            anomalies['error_rate'] = error_analysis
            severity_score += error_analysis['severity']

    # Analyze latency
    if 'latency_ms' in metrics:
        latency = metrics['latency_ms']
        latency_analysis = analyze_latency(latency)
        if latency_analysis['is_anomalous']:
            anomalies['latency_ms'] = latency_analysis
            severity_score += latency_analysis['severity']

    # Analyze request rate
    if 'request_rate' in metrics:
        req_rate = metrics['request_rate']
        req_rate_analysis = analyze_request_rate(req_rate)
        if req_rate_analysis['is_anomalous']:
            anomalies['request_rate'] = req_rate_analysis
            severity_score += req_rate_analysis['severity']

    # Determine if this is an incident (severity >= 2)
    is_incident = severity_score >= 2

    return {
        'has_anomalies': len(anomalies) > 0,
        'anomalies': anomalies,
        'severity_score': severity_score,
        'is_incident': is_incident,
        'metrics': metrics
    }


def analyze_cpu(cpu_utilization: float) -> Dict[str, Any]:
    """
    Analyze CPU utilization

    Args:
        cpu_utilization: CPU usage percentage (0-100)

    Returns:
        Analysis result
    """
    is_anomalous = False
    severity = 0
    description = "Normal"

    if cpu_utilization >= 95:
        is_anomalous = True
        severity = 2
        description = "Critical: CPU near capacity"
    elif cpu_utilization >= 85:
        is_anomalous = True
        severity = 1
        description = "High: CPU under heavy load"
    elif cpu_utilization >= 70:
        is_anomalous = True
        severity = 0.5
        description = "Elevated: CPU usage above normal"

    return {
        'is_anomalous': is_anomalous,
        'severity': severity,
        'value': cpu_utilization,
        'threshold_breached': cpu_utilization if is_anomalous else None,
        'description': description
    }


def analyze_memory(memory_utilization: float) -> Dict[str, Any]:
    """
    Analyze memory utilization

    Args:
        memory_utilization: Memory usage percentage (0-100)

    Returns:
        Analysis result
    """
    is_anomalous = False
    severity = 0
    description = "Normal"

    if memory_utilization >= 95:
        is_anomalous = True
        severity = 2
        description = "Critical: Memory near capacity (risk of OOM)"
    elif memory_utilization >= 85:
        is_anomalous = True
        severity = 1
        description = "High: Memory usage elevated"
    elif memory_utilization >= 75:
        is_anomalous = True
        severity = 0.5
        description = "Elevated: Memory usage above normal"

    return {
        'is_anomalous': is_anomalous,
        'severity': severity,
        'value': memory_utilization,
        'threshold_breached': memory_utilization if is_anomalous else None,
        'description': description
    }


def analyze_error_rate(error_rate: float) -> Dict[str, Any]:
    """
    Analyze error rate

    Args:
        error_rate: Error rate (0.0 - 1.0, where 1.0 = 100%)

    Returns:
        Analysis result
    """
    is_anomalous = False
    severity = 0
    description = "Normal"

    if error_rate >= 0.20:  # 20% error rate
        is_anomalous = True
        severity = 2
        description = "Critical: Very high error rate"
    elif error_rate >= 0.10:  # 10% error rate
        is_anomalous = True
        severity = 1
        description = "High: Elevated error rate"
    elif error_rate >= 0.05:  # 5% error rate
        is_anomalous = True
        severity = 0.5
        description = "Elevated: Error rate above baseline"

    return {
        'is_anomalous': is_anomalous,
        'severity': severity,
        'value': error_rate,
        'threshold_breached': error_rate if is_anomalous else None,
        'description': description
    }


def analyze_latency(latency_ms: float) -> Dict[str, Any]:
    """
    Analyze latency

    Args:
        latency_ms: Latency in milliseconds

    Returns:
        Analysis result
    """
    is_anomalous = False
    severity = 0
    description = "Normal"

    if latency_ms >= 5000:  # 5 seconds
        is_anomalous = True
        severity = 2
        description = "Critical: Very high latency (timeout risk)"
    elif latency_ms >= 2000:  # 2 seconds
        is_anomalous = True
        severity = 1
        description = "High: Elevated latency"
    elif latency_ms >= 1000:  # 1 second
        is_anomalous = True
        severity = 0.5
        description = "Elevated: Latency above normal"

    return {
        'is_anomalous': is_anomalous,
        'severity': severity,
        'value': latency_ms,
        'threshold_breached': latency_ms if is_anomalous else None,
        'description': description
    }


def analyze_request_rate(request_rate: float) -> Dict[str, Any]:
    """
    Analyze request rate (looking for drops or spikes)

    Args:
        request_rate: Requests per second

    Returns:
        Analysis result
    """
    is_anomalous = False
    severity = 0
    description = "Normal"

    # This is a simplified version - in production, compare against baseline
    # For now, detect very low rates (possible service degradation)
    if request_rate < 1:  # Less than 1 req/s suggests service issues
        is_anomalous = True
        severity = 1
        description = "Low: Request rate dropped significantly"
    elif request_rate > 10000:  # Very high rate (possible attack or spike)
        is_anomalous = True
        severity = 1
        description = "High: Unusual request rate spike"

    return {
        'is_anomalous': is_anomalous,
        'severity': severity,
        'value': request_rate,
        'threshold_breached': request_rate if is_anomalous else None,
        'description': description
    }


def get_anomaly_summary(analysis: Dict[str, Any]) -> str:
    """
    Generate human-readable summary of anomalies

    Args:
        analysis: Metrics analysis result

    Returns:
        Summary string
    """
    if not analysis['has_anomalies']:
        return "No anomalies detected"

    summaries = []
    for metric_name, anomaly in analysis['anomalies'].items():
        summaries.append(f"{metric_name}: {anomaly['description']}")

    return "; ".join(summaries)


def compute_incident_priority(analysis: Dict[str, Any]) -> str:
    """
    Compute incident priority based on severity

    Args:
        analysis: Metrics analysis result

    Returns:
        Priority level: P0 (Critical), P1 (High), P2 (Medium), P3 (Low)
    """
    severity = analysis['severity_score']

    if severity >= 3:
        return "P0"  # Critical - multiple critical anomalies
    elif severity >= 2:
        return "P1"  # High - at least one critical or multiple high
    elif severity >= 1:
        return "P2"  # Medium - at least one high or multiple elevated
    else:
        return "P3"  # Low - minor anomalies


def get_metric_context_for_query(analysis: Dict[str, Any]) -> List[str]:
    """
    Generate metric context strings for RAG query enhancement

    Args:
        analysis: Metrics analysis result

    Returns:
        List of context strings
    """
    context = []

    if not analysis['has_anomalies']:
        return context

    for metric_name, anomaly in analysis['anomalies'].items():
        # Create descriptive context
        if metric_name == 'cpu_utilization':
            context.append(f"high CPU usage {anomaly['value']}%")
        elif metric_name == 'memory_utilization':
            context.append(f"high memory usage {anomaly['value']}%")
        elif metric_name == 'error_rate':
            context.append(f"elevated error rate {anomaly['value']:.1%}")
        elif metric_name == 'latency_ms':
            context.append(f"high latency {anomaly['value']}ms")
        elif metric_name == 'request_rate':
            if anomaly['value'] < 10:
                context.append(f"low request rate {anomaly['value']} req/s")
            else:
                context.append(f"high request rate {anomaly['value']} req/s")

    return context


def check_metric_alignment(
    root_cause: str,
    analysis: Dict[str, Any]
) -> List[str]:
    """
    Check which metrics align with diagnosed root cause

    Args:
        root_cause: Diagnosed root cause text
        analysis: Metrics analysis result

    Returns:
        List of aligned metric names
    """
    if not analysis['has_anomalies']:
        return []

    aligned = []
    root_cause_lower = root_cause.lower()

    # Check each anomalous metric for alignment
    for metric_name, anomaly in analysis['anomalies'].items():
        if metric_name == 'cpu_utilization' and any(keyword in root_cause_lower for keyword in ['cpu', 'processor', 'computation']):
            aligned.append('cpu_utilization')

        elif metric_name == 'memory_utilization' and any(keyword in root_cause_lower for keyword in ['memory', 'heap', 'oom', 'leak']):
            aligned.append('memory_utilization')

        elif metric_name == 'error_rate' and any(keyword in root_cause_lower for keyword in ['error', 'failure', 'exception', 'crash']):
            aligned.append('error_rate')

        elif metric_name == 'latency_ms' and any(keyword in root_cause_lower for keyword in ['timeout', 'latency', 'slow', 'delay', 'performance']):
            aligned.append('latency_ms')

        elif metric_name == 'request_rate' and any(keyword in root_cause_lower for keyword in ['traffic', 'load', 'requests', 'throttle', 'rate limit']):
            aligned.append('request_rate')

    return aligned


# Example metrics input:
# {
#   "cpu_utilization": 85,
#   "memory_utilization": 78,
#   "error_rate": 0.15,
#   "latency_ms": 650,
#   "request_rate": 1250
# }

# Example analysis output:
# {
#   "has_anomalies": True,
#   "anomalies": {
#     "cpu_utilization": {
#       "is_anomalous": True,
#       "severity": 1,
#       "value": 85,
#       "threshold_breached": 85,
#       "description": "High: CPU under heavy load"
#     },
#     "error_rate": {
#       "is_anomalous": True,
#       "severity": 1,
#       "value": 0.15,
#       "threshold_breached": 0.15,
#       "description": "High: Elevated error rate"
#     }
#   },
#   "severity_score": 2,
#   "is_incident": True
# }
