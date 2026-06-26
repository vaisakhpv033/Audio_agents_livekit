# Use an official lightweight Python image
FROM python:3.12-slim

# Copy the uv binary from the official image for fast installations
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory inside the container
WORKDIR /app

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv sync (installs into a virtual environment at /app/.venv)
RUN uv sync --frozen --no-cache

# Copy the rest of the application code
COPY . .

# Ensure the virtual environment's binaries are preferred in the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Expose port 8000
EXPOSE 8000

# Run FastAPI via uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
