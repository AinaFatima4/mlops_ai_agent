FROM python:3.12-slim

RUN pip install --no-cache-dir \
    mlflow==3.18.0 \
    "psycopg[binary]==3.3.9" \
    boto3==1.44.3

RUN useradd --create-home --shell /usr/sbin/nologin mlflow
USER mlflow

EXPOSE 5000
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000"]
