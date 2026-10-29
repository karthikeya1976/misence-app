# One image, two roles (same code, different command) — mirrors the redactor-api / redactor-celery systemd units.
#   API:    docker run -p 8088:8088 --env-file .env misence-backend
#   Worker: docker run --env-file .env misence-backend celery -A app.tasks worker --loglevel=info --pool=solo
# Build context is backend/:  docker build -t misence-backend backend/
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Never run as root; credentials come from the environment / ECS task role, not from files in the image.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8088
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
