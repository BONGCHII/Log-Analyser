"""
Log Parser Module
Parses and extracts structured information from log messages
"""

import re
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def parse_log_message(log: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse log message and extract structured information

    Args:
        log: Raw log dictionary

    Returns:
        Parsed log with extracted fields
    """
    parsed = {
        'original_message': log.get('message', ''),
        'error_message': '',
        'error_type': '',
        'error_code': None,
        'service': log.get('service', 'unknown'),
        'timestamp': log.get('timestamp', datetime.utcnow().isoformat()),
        'level': log.get('level', 'ERROR'),
        'context': {}
    }

    message = log.get('message', '')

    # Extract error type (exception class name)
    parsed['error_type'] = extract_error_type(message)

    # Extract error code if present
    parsed['error_code'] = extract_error_code(message)

    # Clean and normalize error message
    parsed['error_message'] = clean_error_message(message)

    # Extract contextual information
    parsed['context'] = extract_context(log)

    # Extract stack trace if available
    if 'stack_trace' in log:
        parsed['stack_trace'] = log['stack_trace']
        parsed['stack_summary'] = summarize_stack_trace(log['stack_trace'])

    # Extract metrics if available
    if 'metrics' in log:
        parsed['metrics'] = log['metrics']

    return parsed


def extract_error_type(message: str) -> str:
    """
    Extract error type/exception class from message

    Args:
        message: Error message

    Returns:
        Error type string
    """
    # Common error type patterns
    patterns = [
        r'(\w+Exception)',
        r'(\w+Error)',
        r'(\w+Timeout)',
        r'(\w+Failure)',
        r'ERROR:\s*(\w+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1)

    # Check for common error keywords
    error_keywords = {
        'timeout': 'TimeoutError',
        'connection': 'ConnectionError',
        'memory': 'MemoryError',
        'database': 'DatabaseError',
        'authentication': 'AuthenticationError',
        'authorization': 'AuthorizationError',
        'not found': 'NotFoundError',
        'invalid': 'ValidationError',
        'null pointer': 'NullPointerException',
        'out of bounds': 'IndexError',
    }

    message_lower = message.lower()
    for keyword, error_type in error_keywords.items():
        if keyword in message_lower:
            return error_type

    return 'UnknownError'


def extract_error_code(message: str) -> Optional[str]:
    """
    Extract error code from message (e.g., HTTP status codes, custom codes)

    Args:
        message: Error message

    Returns:
        Error code string or None
    """
    # HTTP status codes
    http_match = re.search(r'\b(4\d{2}|5\d{2})\b', message)
    if http_match:
        return f"HTTP_{http_match.group(1)}"

    # Custom error codes (e.g., ERR-1234, ERROR_CODE_5678)
    code_patterns = [
        r'ERR[-_](\d+)',
        r'ERROR[-_]CODE[-_](\d+)',
        r'CODE:\s*(\d+)',
    ]

    for pattern in code_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return f"ERR_{match.group(1)}"

    return None


def clean_error_message(message: str) -> str:
    """
    Clean and normalize error message

    Args:
        message: Raw error message

    Returns:
        Cleaned error message
    """
    # Remove timestamps
    cleaned = re.sub(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[.,]\d{3}', '', message)

    # Remove log level prefixes
    cleaned = re.sub(r'^(ERROR|WARN|INFO|DEBUG):\s*', '', cleaned, flags=re.IGNORECASE)

    # Remove thread IDs
    cleaned = re.sub(r'\[thread-\d+\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\[tid:\d+\]', '', cleaned, flags=re.IGNORECASE)

    # Remove file paths
    cleaned = re.sub(r'[/\\][\w/\\.-]+\.py', '[file]', cleaned)
    cleaned = re.sub(r'[/\\][\w/\\.-]+\.java', '[file]', cleaned)

    # Remove line numbers
    cleaned = re.sub(r'line\s+\d+', 'line [N]', cleaned, flags=re.IGNORECASE)

    # Remove request IDs / correlation IDs
    cleaned = re.sub(r'request[_-]?id[:\s]+[\w-]+', 'request_id:[ID]', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'correlation[_-]?id[:\s]+[\w-]+', 'correlation_id:[ID]', cleaned, flags=re.IGNORECASE)

    # Remove UUIDs
    cleaned = re.sub(
        r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b',
        '[UUID]',
        cleaned
    )

    # Remove IP addresses
    cleaned = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', cleaned)

    # Remove specific numeric values (keep general numbers)
    cleaned = re.sub(r':\s*\d+\.\d+', ': [NUM]', cleaned)  # Decimals
    cleaned = re.sub(r'=\s*\d+', '=[NUM]', cleaned)  # Assignments

    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned


def extract_context(log: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract contextual information from log

    Args:
        log: Log dictionary

    Returns:
        Context dictionary
    """
    context = {}

    # Extract user information
    if 'user_id' in log:
        context['user_id'] = log['user_id']
    if 'username' in log:
        context['username'] = log['username']

    # Extract request information
    if 'request_id' in log:
        context['request_id'] = log['request_id']
    if 'correlation_id' in log:
        context['correlation_id'] = log['correlation_id']
    if 'trace_id' in log:
        context['trace_id'] = log['trace_id']

    # Extract endpoint information
    if 'endpoint' in log:
        context['endpoint'] = log['endpoint']
    if 'method' in log:
        context['method'] = log['method']
    if 'url' in log:
        context['url'] = log['url']

    # Extract environment
    if 'environment' in log:
        context['environment'] = log['environment']
    if 'region' in log:
        context['region'] = log['region']

    # Extract additional metadata
    if 'metadata' in log and isinstance(log['metadata'], dict):
        context.update(log['metadata'])

    return context


def summarize_stack_trace(stack_trace: str, max_frames: int = 5) -> List[str]:
    """
    Summarize stack trace to most relevant frames

    Args:
        stack_trace: Full stack trace string
        max_frames: Maximum number of frames to include

    Returns:
        List of summarized stack frames
    """
    if not stack_trace:
        return []

    frames = []

    # Split into lines
    lines = stack_trace.strip().split('\n')

    for line in lines:
        # Look for frame indicators
        if re.match(r'\s+at\s+', line) or re.match(r'\s+File\s+"', line):
            # Extract function/method name
            func_match = re.search(r'at\s+([\w.<>]+)', line)
            if func_match:
                frames.append(func_match.group(1))
                continue

            file_match = re.search(r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\w+)', line)
            if file_match:
                filename = file_match.group(1).split('/')[-1]
                line_num = file_match.group(2)
                func_name = file_match.group(3)
                frames.append(f"{filename}:{line_num} in {func_name}")

    # Return top frames (skip common framework frames at the top)
    return frames[-max_frames:] if len(frames) > max_frames else frames


def extract_numeric_values(message: str) -> Dict[str, float]:
    """
    Extract numeric values from error message

    Args:
        message: Error message

    Returns:
        Dictionary of extracted numeric values
    """
    values = {}

    # Timeout values
    timeout_match = re.search(r'timeout.*?(\d+)\s*(ms|s|seconds?|milliseconds?)', message, re.IGNORECASE)
    if timeout_match:
        value = float(timeout_match.group(1))
        unit = timeout_match.group(2).lower()
        if 'ms' in unit or 'milli' in unit:
            values['timeout_ms'] = value
        else:
            values['timeout_ms'] = value * 1000

    # Memory values
    memory_match = re.search(r'memory.*?(\d+)\s*(MB|GB|KB)', message, re.IGNORECASE)
    if memory_match:
        value = float(memory_match.group(1))
        unit = memory_match.group(2).upper()
        if unit == 'GB':
            values['memory_mb'] = value * 1024
        elif unit == 'KB':
            values['memory_mb'] = value / 1024
        else:
            values['memory_mb'] = value

    # Connection counts
    conn_match = re.search(r'connections?.*?(\d+)', message, re.IGNORECASE)
    if conn_match:
        values['connection_count'] = float(conn_match.group(1))

    # Retry counts
    retry_match = re.search(r'retries?.*?(\d+)', message, re.IGNORECASE)
    if retry_match:
        values['retry_count'] = float(retry_match.group(1))

    return values


def categorize_error(parsed_log: Dict[str, Any]) -> str:
    """
    Categorize error into broad categories

    Args:
        parsed_log: Parsed log dictionary

    Returns:
        Error category string
    """
    message = parsed_log.get('error_message', '').lower()
    error_type = parsed_log.get('error_type', '').lower()

    # Category keywords
    categories = {
        'database': ['database', 'sql', 'connection pool', 'query', 'deadlock', 'transaction'],
        'network': ['timeout', 'connection refused', 'network', 'socket', 'unreachable'],
        'memory': ['memory', 'heap', 'out of memory', 'oom', 'garbage collection'],
        'authentication': ['authentication', 'authorization', 'unauthorized', 'forbidden', 'token', 'credentials'],
        'configuration': ['configuration', 'config', 'missing property', 'invalid setting'],
        'external_service': ['api', 'service unavailable', 'downstream', 'third party', 'gateway'],
        'validation': ['validation', 'invalid', 'malformed', 'parsing error'],
        'resource': ['resource', 'file not found', 'disk', 'quota exceeded'],
    }

    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in message or keyword in error_type:
                return category

    return 'general'


# Example parsed output:
# {
#   "original_message": "ERROR: Database connection timeout after 30s (connection_id=abc123)",
#   "error_message": "Database connection timeout after [NUM]s (connection_id=[ID])",
#   "error_type": "TimeoutError",
#   "error_code": None,
#   "service": "payment-api",
#   "timestamp": "2024-01-15T14:32:15Z",
#   "level": "ERROR",
#   "context": {
#     "request_id": "req-789",
#     "endpoint": "/api/payments"
#   }
# }
