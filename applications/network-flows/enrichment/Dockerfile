FROM python:3.14.7-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/rokoucha/materia"
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY enrich.py .
USER 10001:10001
CMD ["python", "-u", "enrich.py"]
