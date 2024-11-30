ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS build
RUN pip install poetry && \
    python3 -m venv /venv

# Install poetry, export requirements.txt and install them into venv
FROM build AS build-env
COPY poetry.lock pyproject.toml ./
RUN poetry config virtualenvs.in-project true && \
    poetry export --only main --without-hashes --output /tmp/requirements.txt && \
    /venv/bin/pip install --no-cache-dir --no-deps -r /tmp/requirements.txt

# Use distroless image for small footprint and security
FROM gcr.io/distroless/python3-debian12:nonroot
ARG PYTHON_VERSION
COPY --from=build-env /venv/lib/python$PYTHON_VERSION/site-packages /usr/local/lib/python$PYTHON_VERSION/site-packages
COPY ./app/main.py /app/main.py
WORKDIR /app
ENV PYTHONPATH=/usr/local/lib/python$PYTHON_VERSION/site-packages
CMD ["main.py"]
