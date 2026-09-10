FROM python:3.12-slim
RUN pip install --no-cache-dir boto3
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY capture.py tdnet_capture.py boj_capture.py edgar_capture.py us_capture.py heartbeat.py ./
# CAPTURE_CMD picks the collector; CAPTURE_ARGS its window
CMD ["sh", "-c", "python ${CAPTURE_CMD:-capture.py} ${CAPTURE_ARGS:---days 7}"]
