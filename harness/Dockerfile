# The marketing agent: the cloud agent (server + web UI) with the `mkt`
# command line tool, ffmpeg and a headless Chromium on the same machine,
# run with AGENT_SANDBOX=off like Everything Agent (one user, commands on
# the control plane). Build from the repo root:
#
#   GH_TOKEN=$(gh auth token) fly deploy -c products/marketing/fly.toml \
#       --build-secret GH_TOKEN="$GH_TOKEN"
#
# GH_TOKEN reads tamaratran/marketing-agent at build time (pip install from
# git); it is not in the image. The repo is public since 2026-11-04, so the
# campaign.toml fetch falls back to an unauthenticated GET when the short-lived
# installation token is refused by raw.githubusercontent.com (a 404).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python3 -m playwright install --with-deps chromium

# The marketing loop: `mkt` and its campaign.toml (the product, niche and
# account it works for). MKT_CAMPAIGN points `mkt` at the copy.
ARG MKT_REF=main
RUN --mount=type=secret,id=GH_TOKEN \
    TOKEN="$(cat /run/secrets/GH_TOKEN)" \
    && pip install --no-cache-dir \
        "git+https://x-access-token:${TOKEN}@github.com/tamaratran/marketing-agent@${MKT_REF}" \
    && CAMPAIGN="https://raw.githubusercontent.com/tamaratran/marketing-agent/${MKT_REF}/campaign.toml" \
    && (curl -fsSL -H "Authorization: Bearer ${TOKEN}" "$CAMPAIGN" -o /app/campaign.toml \
        || curl -fsSL "$CAMPAIGN" -o /app/campaign.toml)

COPY agent/ agent/
COPY server/ server/
COPY web/ web/
COPY products/ products/

ENV AGENT_SESSIONS_ROOT=/data \
    AGENT_SANDBOX=off \
    AGENT_PRODUCT=marketing \
    AGENT_CHROMIUM_CDP_PORT=9222 \
    EMAIL_AUTH_ENABLED=true \
    MKT_CAMPAIGN=/app/campaign.toml \
    PYTHONUNBUFFERED=1
EXPOSE 8321
CMD ["python", "-m", "uvicorn", "server.main:app", \
     "--host", "0.0.0.0", "--port", "8321", "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
