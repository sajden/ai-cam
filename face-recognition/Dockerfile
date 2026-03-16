FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/lib/wsl/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/dist-packages/nvidia/cudnn/lib

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/python3 /usr/bin/python && \
    python3 -m pip install --upgrade pip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download InsightFace buffalo_l model at build time so first request is fast
RUN python3 -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']).prepare(ctx_id=-1, det_size=(640,640))"

COPY app/ ./app/

EXPOSE 8082

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
