# The orchestrator: starts one terminal container per account. Standard
# library only. It needs the Docker socket, which is root on the host, so it
# does nothing else. Build context: the repository root.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY agent/brokers.json /app/brokers.json
COPY orchestrator/orchestrator.py /app/orchestrator.py
VOLUME ["/state"]
ENTRYPOINT ["python3", "-u", "/app/orchestrator.py"]
