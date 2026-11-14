FROM apache/airflow:3.4.0-python3.12

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Separate environment for training code so its packages never clash with Airflow's own
COPY docker/training-requirements.txt /tmp/training-requirements.txt
RUN python -m venv /opt/training-venv \
    && /opt/training-venv/bin/pip install --no-cache-dir -r /tmp/training-requirements.txt

USER airflow
