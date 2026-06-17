FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
# GID 989 = groupe docker sur l'hôte (accès /var/run/docker.sock)
RUN groupadd --gid 989 dockerhost && \
    useradd --system --uid 1001 --gid dockerhost --no-create-home app
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
