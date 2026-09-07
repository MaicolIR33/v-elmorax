FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/velmorax

RUN groupadd --system velmorax && useradd --system --gid velmorax --home /opt/velmorax velmorax

COPY pyproject.toml README.md ./
COPY app ./app
RUN python -m pip install --upgrade pip && python -m pip install .

COPY deploy/entrypoint.sh /usr/local/bin/velmorax-entrypoint
RUN chmod 0555 /usr/local/bin/velmorax-entrypoint && chown -R velmorax:velmorax /opt/velmorax

USER velmorax
EXPOSE 8000

ENTRYPOINT ["velmorax-entrypoint"]
