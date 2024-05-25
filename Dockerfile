FROM python:3.12-bookworm as build

WORKDIR /app

COPY poetry.lock pyproject.toml ./

# Install poetry, export requirements.txt and install them into venv
RUN pip install poetry && \
    poetry config virtualenvs.in-project true && \
    poetry export --only main --without-hashes --output /tmp/requirements.txt && \
    python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --no-deps -r /tmp/requirements.txt

# Use distroless image for small footprint and security
FROM python:3.12-alpine
COPY --from=build /venv /venv
COPY app/main.py /app/
WORKDIR /app
ENTRYPOINT ["/venv/bin/python", "main.py"]
