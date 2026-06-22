# Container image for myinventory.
#
# A scan runs as a short-lived job: mount a config and an output directory, and
# the entrypoint is the CLI. The image bundles the optional backends ([all]) and
# the `d2` binary so `report --html` produces SVGs out of the box.
#
#   docker build -t myinventory .
#   docker run --rm --network host \
#     -v "$PWD/myinventory.yaml:/etc/myinventory/config.yaml:ro" \
#     -v "$PWD/out:/var/lib/myinventory/out" \
#     -e PROXMOX_TOKEN \
#     myinventory report -c /etc/myinventory/config.yaml -o /var/lib/myinventory/out --html

FROM python:3.12-slim AS base

# Runtime tools: `ping`/`arp` for the dependency-free sweeps, `d2` for HTML SVGs.
# libvirt headers are only needed by the [virt] extra's libvirt-python build, so
# they live in a throwaway builder stage.
FROM base AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc pkg-config libvirt-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[all]"

FROM base AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping net-tools curl libvirt0 \
    && curl -fsSL https://d2lang.com/install.sh | sh -s -- \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv

# Run unprivileged. `report` writes only to the mounted output directory.
RUN useradd --create-home --uid 10001 inventory
USER inventory
WORKDIR /var/lib/myinventory

ENTRYPOINT ["myinventory"]
CMD ["--help"]
