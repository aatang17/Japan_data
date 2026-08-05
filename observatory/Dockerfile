FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
COPY start.sh ./
RUN chmod +x start.sh

# data/ is a mounted volume in production: the DuckDB file and the raw
# source archive must survive redeploys.
ENV PYTHONUNBUFFERED=1

CMD ["./start.sh"]
