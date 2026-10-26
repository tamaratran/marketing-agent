FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md campaign.toml ./
COPY marketing_agent ./marketing_agent
RUN pip install --no-cache-dir ".[api]"
ENV MKT_DATA_DIR=/data PORT=8080 MKT_CAMPAIGN=/app/campaign.toml
EXPOSE 8080
CMD ["sh", "-c", "uvicorn marketing_agent.api:app --host 0.0.0.0 --port ${PORT}"]
