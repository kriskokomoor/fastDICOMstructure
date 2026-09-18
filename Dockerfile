# syntax=docker/dockerfile:1
#
# S1.7 -- Container Portability. Proves the frozen S1.6 CLI
# (`python -m fastdicomstructure run --config ... [--json]`) executes
# unchanged inside a container: Docker contributes only packaging and
# environmental filesystem binding, never a second DICOM, policy,
# configuration, adapter, or execution path. See
# docs/architecture/S1_7_CONTAINER_PORTABILITY_DESIGN_CHECKPOINT.md.
#
# Two source trees are needed -- this repository and its sibling
# fastDICOMattrs checkout (the DICOM parser/writer/C ABI, extracted out of
# this repository at the A0 semantic-engine extraction). fastDICOMattrs is
# never vendored into this repository, so the build requires one named
# BuildKit build context pointing at that sibling checkout -- the identical
# pattern fastDICOMgateway's own Dockerfile already uses one layer up this
# same dependency chain (see that repository's Dockerfile), adapted here for
# a one-shot CLI image rather than a long-running HTTP service. Build from
# inside this repository with:
#
#   docker build -f Dockerfile \
#       --build-context attrs=../fastDICOMattrs \
#       -t fastdicomstructure:s1.7 .
#
# Both stages pin the same base image tag so the compiled C++ shared
# library (built against this image's glibc/libstdc++) and the runtime
# stage that links it stay ABI-compatible.
ARG BASE_IMAGE=python:3.12-slim-bookworm

# ---------------------------------------------------------------------------
# Stage 1: compile fastDICOMattrs' C++ core + C ABI shared library. Tests/
# bench are disabled (FDS_BUILD_TESTS/FDS_BUILD_BENCH=OFF) -- this stage only
# needs to produce libfastdicomattrs_c.so, not run that repository's own
# test suite (already validated on its own, frozen commit). This build
# tooling (compiler, CMake, Ninja) never reaches the runtime stage.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS attrs-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/fastDICOMattrs
COPY --from=attrs . .

RUN rm -rf build \
    && cmake -S . -B container-build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DFDS_BUILD_TESTS=OFF \
        -DFDS_BUILD_BENCH=OFF \
        -DFDS_BUILD_ABI=ON \
    && cmake --build container-build --parallel \
    && cmake --install container-build --prefix /opt/fastdicomattrs-install \
    && mkdir -p /opt/fastdicomattrs-install/python-package \
    && cp -r python/fastdicomattrs /opt/fastdicomattrs-install/python-package/ \
    && rm -rf /opt/fastdicomattrs-install/python-package/fastdicomattrs/__pycache__

# ---------------------------------------------------------------------------
# Stage 2: runtime image. Python + fastDICOMattrs' compiled shared library +
# its plain-copied Python ctypes binding (no wheel exists for it -- see the
# design checkpoint's packaging analysis; only libstdc++6 is needed at
# runtime, no compiler) + fastDICOMstructure installed as a real,
# non-editable wheel built directly in this stage from its own new, minimal
# pyproject.toml (pure Python -- no discardable toolchain needed, so no
# separate Structure builder stage). No PYTHONPATH dependency, no mounted
# source tree, no pydicom/DCMTK/cloud SDK/credentials/test corpus -- see
# .dockerignore for what never reaches this image's build context at all.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=attrs-builder /opt/fastdicomattrs-install/lib/ /usr/local/lib/
# Base-image-version-coupled path: python:3.12-* always exposes this exact
# site-packages location.
COPY --from=attrs-builder /opt/fastdicomattrs-install/python-package/fastdicomattrs \
    /usr/local/lib/python3.12/site-packages/fastdicomattrs
RUN ldconfig

WORKDIR /src/fastDICOMstructure
COPY pyproject.toml README.md LICENSE ./
COPY python ./python
RUN pip install --no-cache-dir . \
    && rm -rf /src/fastDICOMstructure

ENV FASTDICOMATTRS_LIB=/usr/local/lib/libfastdicomattrs_c.so \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root, unprivileged: no home directory, no login shell -- the CLI
# needs no writable path of its own beyond whatever destination the
# operator bind-mounts and configures (see the design checkpoint's runtime-
# user analysis).
RUN groupadd --gid 1000 fdsuser \
    && useradd --uid 1000 --gid fdsuser --no-create-home \
        --shell /usr/sbin/nologin fdsuser
USER fdsuser:fdsuser

WORKDIR /work

# Exec-form, no shell, no wrapper -- arguments given to `docker run IMAGE ...`
# reach the frozen S1.6 CLI's own argv completely unmodified. This is
# freeze-critical: no translation layer of any kind exists between this
# ENTRYPOINT and fastdicomstructure.cli.main().
ENTRYPOINT ["python", "-m", "fastdicomstructure"]
