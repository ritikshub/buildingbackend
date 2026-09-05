# The sandbox image: Python + the lesson dependencies + the Linux tools Phase 1 teaches.
# CPU-only, multi-arch (runs natively on Apple Silicon). No GPU, nothing global.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

# Phase 1 (Linux and the Command Line) runs its Use It halves on real tools:
# strace, curl, ss/ip, dig, tcpdump, nc, jq, ps/top/free, lsof, rsync, ssh, ...
# python:slim is Debian, so apt is the package manager the lesson on packages teaches.
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash-completion bsdextrautils curl dnsutils file iproute2 iputils-ping jq \
      less lsof nano netcat-openbsd openssh-client procps psmisc rsync shellcheck \
      strace sysstat tcpdump traceroute tree \
    && rm -rf /var/lib/apt/lists/*

# Install deps first so this layer caches unless requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# The repo itself is bind-mounted at runtime (see docker-compose.yml),
# so code edits on your Mac are live inside the container with no rebuild.
CMD ["sleep", "infinity"]
