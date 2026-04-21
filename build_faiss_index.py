#!/usr/bin/env python3
"""
Build FAISS Index from incidents.json
Generates embeddings and uploads index to S3
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

import numpy as np
import boto3
from botocore.exceptions import ClientError
from sentence_transformers import SentenceTransformer
import faiss

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# AWS clients
s3_client = boto3.client('s3')


def load_incidents(file_path: str) -> List[Dict[str, Any]]:
    """
    Load incidents from JSON file

    Args:
        file_path: Path to incidents.json

    Returns:
        List of incident dictionaries
    """
    try:
        logger.info(f"Loading incidents from {file_path}")

        if not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}, creating empty list")
            return []

        with open(file_path, 'r', encoding='utf-8') as f:
            incidents = json.load(f)

        if not isinstance(incidents, list):
            logger.error("incidents.json must be a JSON array")
            sys.exit(1)

        logger.info(f"Loaded {len(incidents)} incidents")
        return incidents

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading incidents: {str(e)}")
        sys.exit(1)


def validate_incidents(incidents: List[Dict[str, Any]]) -> bool:
    """
    Validate incident schema

    Args:
        incidents: List of incidents

    Returns:
        True if valid
    """
    required_fields = ['incident_id', 'service', 'symptoms', 'root_cause']

    for i, incident in enumerate(incidents):
        # Check required fields
        missing = [field for field in required_fields if field not in incident]
        if missing:
            logger.error(f"Incident {i} missing required fields: {missing}")
            logger.error(f"Incident: {incident}")
            return False

        # Check field types
        if not isinstance(incident['incident_id'], str):
            logger.error(f"Incident {i}: incident_id must be string")
            return False

        if not isinstance(incident['service'], str):
            logger.error(f"Incident {i}: service must be string")
            return False

    logger.info("All incidents validated successfully")
    return True


def build_index(incidents: List[Dict[str, Any]]) -> Tuple[faiss.IndexFlatIP, np.ndarray, List[Dict[str, Any]]]:
    """
    Build FAISS index from incidents

    Args:
        incidents: List of incident dictionaries

    Returns:
        Tuple of (FAISS index, embeddings, metadata)
    """
    if len(incidents) == 0:
        logger.warning("No incidents to index")
        return None, None, []

    logger.info("Loading sentence-transformers model: all-MiniLM-L6-v2")
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # Prepare texts for embedding
    logger.info("Preparing texts for embedding")
    texts = []
    metadata = []

    for incident in incidents:
        # Combine service, symptoms, and root_cause for embedding
        text = f"{incident['service']} {incident['symptoms']} {incident['root_cause']}"
        texts.append(text)

        # Store minimal metadata
        metadata.append({
            'incident_id': incident['incident_id'],
            'service': incident['service'],
            'symptoms': incident['symptoms'],
            'root_cause': incident['root_cause'],
            'recommended_actions': incident.get('recommended_actions', []),
            'timestamp': incident.get('timestamp', '')
        })

    # Generate embeddings
    logger.info(f"Generating embeddings for {len(texts)} incidents...")
    embeddings = model.encode(
        texts,
        show_progress_bar=True,
        convert_to_numpy=True,
        batch_size=32
    )

    # Normalize embeddings for cosine similarity
    logger.info("Normalizing embeddings")
    faiss.normalize_L2(embeddings)

    # Create FAISS index
    logger.info("Building FAISS index")
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)  # Inner Product for cosine similarity
    index.add(embeddings)

    logger.info(f"FAISS index built successfully:")
    logger.info(f"  - Dimension: {dimension}")
    logger.info(f"  - Total vectors: {index.ntotal}")
    logger.info(f"  - Index size: ~{index.ntotal * dimension * 4 / 1024:.2f} KB")

    return index, embeddings, metadata


def save_index_locally(index: faiss.IndexFlatIP, metadata: List[Dict[str, Any]], output_dir: str):
    """
    Save FAISS index and metadata locally

    Args:
        index: FAISS index
        metadata: Metadata list
        output_dir: Output directory
    """
    os.makedirs(output_dir, exist_ok=True)

    # Save FAISS index
    index_path = os.path.join(output_dir, 'index.bin')
    logger.info(f"Saving FAISS index to {index_path}")
    faiss.write_index(index, index_path)

    # Save metadata
    metadata_path = os.path.join(output_dir, 'metadata.json')
    logger.info(f"Saving metadata to {metadata_path}")
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    logger.info("Index saved locally")


def upload_to_s3(index: faiss.IndexFlatIP, metadata: List[Dict[str, Any]], bucket: str, prefix: str):
    """
    Upload FAISS index and metadata to S3

    Args:
        index: FAISS index
        metadata: Metadata list
        bucket: S3 bucket name
        prefix: S3 key prefix (e.g., 'faiss/')
    """
    import tempfile

    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save index locally first
        index_path = os.path.join(temp_dir, 'index.bin')
        metadata_path = os.path.join(temp_dir, 'metadata.json')

        logger.info("Saving to temporary files")
        faiss.write_index(index, index_path)

        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # Upload to S3
        index_key = f"{prefix}index.bin"
        metadata_key = f"{prefix}metadata.json"

        try:
            logger.info(f"Uploading index to s3://{bucket}/{index_key}")
            s3_client.upload_file(index_path, bucket, index_key)

            logger.info(f"Uploading metadata to s3://{bucket}/{metadata_key}")
            s3_client.upload_file(metadata_path, bucket, metadata_key)

            logger.info("Upload to S3 completed successfully")

        except ClientError as e:
            logger.error(f"S3 upload error: {e.response['Error']['Message']}")
            raise
        except Exception as e:
            logger.error(f"Unexpected upload error: {str(e)}")
            raise


def test_index(index: faiss.IndexFlatIP, metadata: List[Dict[str, Any]], model: SentenceTransformer):
    """
    Test the index with sample queries

    Args:
        index: FAISS index
        metadata: Metadata list
        model: SentenceTransformer model
    """
    logger.info("\n=== Testing Index ===")

    test_queries = [
        "database connection timeout",
        "memory leak",
        "API timeout"
    ]

    for query in test_queries:
        logger.info(f"\nQuery: '{query}'")

        # Encode query
        query_embedding = model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)

        # Search
        distances, indices = index.search(query_embedding, k=3)

        logger.info("Top 3 results:")
        for i, (distance, idx) in enumerate(zip(distances[0], indices[0]), 1):
            if idx != -1 and idx < len(metadata):
                incident = metadata[idx]
                logger.info(f"  {i}. [{incident['incident_id']}] {incident['service']}")
                logger.info(f"     Similarity: {distance:.3f}")
                logger.info(f"     Symptoms: {incident['symptoms'][:80]}...")


def print_statistics(incidents: List[Dict[str, Any]]):
    """
    Print statistics about incidents

    Args:
        incidents: List of incidents
    """
    logger.info("\n=== Incident Statistics ===")
    logger.info(f"Total incidents: {len(incidents)}")

    if len(incidents) == 0:
        return

    # Service distribution
    services = {}
    for incident in incidents:
        service = incident.get('service', 'unknown')
        services[service] = services.get(service, 0) + 1

    logger.info(f"\nService distribution:")
    for service, count in sorted(services.items(), key=lambda x: x[1], reverse=True)[:10]:
        logger.info(f"  {service}: {count}")

    # Check for duplicates
    incident_ids = [inc.get('incident_id', '') for inc in incidents]
    if len(incident_ids) != len(set(incident_ids)):
        logger.warning("Duplicate incident IDs found!")


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Build FAISS index from incidents.json')
    parser.add_argument(
        '--input',
        default='data/incidents.json',
        help='Path to incidents.json (default: data/incidents.json)'
    )
    parser.add_argument(
        '--output-dir',
        default='faiss_output',
        help='Local output directory (default: faiss_output)'
    )
    parser.add_argument(
        '--s3-bucket',
        default=os.environ.get('S3_BUCKET'),
        help='S3 bucket name (default: from S3_BUCKET env var)'
    )
    parser.add_argument(
        '--s3-prefix',
        default='faiss/',
        help='S3 key prefix (default: faiss/)'
    )
    parser.add_argument(
        '--upload',
        action='store_true',
        help='Upload to S3 after building'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run test queries after building'
    )
    parser.add_argument(
        '--skip-validation',
        action='store_true',
        help='Skip incident validation'
    )

    args = parser.parse_args()

    # Load incidents
    incidents = load_incidents(args.input)

    if len(incidents) == 0:
        logger.warning("No incidents loaded. Creating empty index is not recommended.")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            logger.info("Aborted")
            sys.exit(0)

    # Print statistics
    print_statistics(incidents)

    # Validate incidents
    if not args.skip_validation:
        if not validate_incidents(incidents):
            logger.error("Validation failed")
            sys.exit(1)

    # Build index
    index, embeddings, metadata = build_index(incidents)

    if index is None:
        logger.error("Failed to build index")
        sys.exit(1)

    # Save locally
    save_index_locally(index, metadata, args.output_dir)

    # Upload to S3
    if args.upload:
        if not args.s3_bucket:
            logger.error("S3 bucket not specified. Use --s3-bucket or set S3_BUCKET env var")
            sys.exit(1)

        upload_to_s3(index, metadata, args.s3_bucket, args.s3_prefix)

    # Test index
    if args.test and len(incidents) > 0:
        model = SentenceTransformer('all-MiniLM-L6-v2')
        test_index(index, metadata, model)

    logger.info("\n=== Build Complete ===")
    logger.info(f"Local output: {args.output_dir}/")
    if args.upload:
        logger.info(f"S3 location: s3://{args.s3_bucket}/{args.s3_prefix}")


if __name__ == '__main__':
    main()
