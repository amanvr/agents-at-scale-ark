FROM python:3.12-slim

WORKDIR /app

# Install uv for faster dependency resolution
RUN pip install --no-cache-dir uv

# Copy ARK SDK wheel from build context (devspace sets context to repo root)
COPY out/ark-sdk/py-sdk/dist/ark_sdk-0.1.53-py3-none-any.whl /tmp/ark_sdk-0.1.53-py3-none-any.whl

# Copy service files
COPY services/executor-pod-agent/pyproject.toml ./
COPY services/executor-pod-agent/README.md ./
COPY services/executor-pod-agent/src/ ./src/

# Update pyproject.toml to use local wheel (update both version and path)
RUN sed -i 's|path = "../../out/ark-sdk/py-sdk/dist/ark_sdk-0.1.52-py3-none-any.whl"|path = "/tmp/ark_sdk-0.1.53-py3-none-any.whl"|' pyproject.toml

# Install dependencies using uv
RUN uv pip install --system --no-cache -e .

# Run as non-root user
RUN useradd -m -u 1000 executor && \
    chown -R executor:executor /app
USER executor

# Expose port
EXPOSE 8000

# Run the executor
CMD ["python", "-m", "pod_executor"]
