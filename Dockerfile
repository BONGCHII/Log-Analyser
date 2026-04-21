# Lambda Container Image for AI Root Cause Analyzer
# Base image: AWS Lambda Python 3.9
FROM public.ecr.aws/lambda/python:3.9

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Install system dependencies
# gcc, g++, cmake needed for compiling Python packages
RUN yum update -y && \
    yum install -y \
    gcc \
    gcc-c++ \
    cmake \
    git \
    && yum clean all && \
    rm -rf /var/cache/yum

# Copy requirements file first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
# Install in specific order to optimize layer caching
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# Install Pillow first (required for torch)
RUN pip3 install --no-cache-dir Pillow==10.0.0

# Install PyTorch CPU-only version (smaller size, faster download)
# Using CPU-only saves ~800MB compared to CUDA version
RUN pip3 install --no-cache-dir \
    torch==2.0.1 \
    --index-url https://download.pytorch.org/whl/cpu

# Install transformers ecosystem (needed for sentence-transformers)
RUN pip3 install --no-cache-dir \
    transformers==4.30.2 \
    tokenizers==0.13.3 \
    huggingface-hub==0.16.4 \
    safetensors==0.3.1

# Install sentence-transformers and FAISS
RUN pip3 install --no-cache-dir \
    sentence-transformers==2.2.2 \
    faiss-cpu==1.7.4

# Install AWS SDK and other dependencies
RUN pip3 install --no-cache-dir \
    boto3==1.28.25 \
    botocore==1.31.25 \
    numpy==1.24.3

# Pre-download the sentence-transformers model to avoid cold start delays
# This downloads ~80MB model during build, not at runtime
RUN python3 -c "from sentence_transformers import SentenceTransformer; \
    model = SentenceTransformer('all-MiniLM-L6-v2'); \
    print('Model downloaded successfully')"

# Copy application code
COPY lambda/ ${LAMBDA_TASK_ROOT}/lambda/
COPY data/ ${LAMBDA_TASK_ROOT}/data/
COPY scripts/ ${LAMBDA_TASK_ROOT}/scripts/

# Set Python path to include lambda directory
ENV PYTHONPATH="${LAMBDA_TASK_ROOT}:${PYTHONPATH}"

# Disable pip warnings
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Optimize Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Lambda handler configuration
CMD ["lambda.handler.lambda_handler"]

# Build instructions:
# ------------------
# 1. Authenticate to ECR:
#    aws ecr get-login-password --region us-east-1 | \
#      docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
#
# 2. Build image:
#    docker build -t rca-analyzer:latest .
#
# 3. Tag image:
#    docker tag rca-analyzer:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/rca-analyzer:latest
#
# 4. Push to ECR:
#    docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/rca-analyzer:latest
#
# 5. Update Lambda function:
#    aws lambda update-function-code \
#      --function-name rca-analyzer \
#      --image-uri <account-id>.dkr.ecr.us-east-1.amazonaws.com/rca-analyzer:latest

# Image size optimization notes:
# ------------------------------
# - Using PyTorch CPU-only: ~500MB saved
# - Pre-downloading model: Faster cold starts
# - No CUDA dependencies: ~300MB saved
# - Minimal system packages: ~100MB saved
# Final image size: ~2.5GB (within Lambda 10GB limit)

# Local testing:
# --------------
# docker run -p 9000:8080 \
#   -e S3_BUCKET=your-bucket \
#   -e KNOWLEDGE_BASE_BUCKET=your-bucket \
#   -e KNOWLEDGE_BASE_KEY=knowledge-base/incidents.json \
#   -e DYNAMODB_TABLE=rca-analysis \
#   -e LOG_LEVEL_FILTER=ERROR,WARN \
#   rca-analyzer:latest
#
# Then invoke:
# curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
#   -d '{"date": "2024-01-15"}'
