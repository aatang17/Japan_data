FROM python:3.12-slim
RUN pip install --no-cache-dir boto3
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY capture.py .
# CAPTURE_ARGS overrides for backfills; default is the self-healing daily window
CMD ["sh", "-c", "python capture.py ${CAPTURE_ARGS:---days 7}"]
