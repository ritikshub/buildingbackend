# The sandbox image: Python + the lesson dependencies.
# CPU-only, multi-arch (runs natively on Apple Silicon). No GPU, nothing global.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

# Install deps first so this layer caches unless requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# The repo itself is bind-mounted at runtime (see docker-compose.yml),
# so code edits on your Mac are live inside the container with no rebuild.
CMD ["sleep", "infinity"]
