#!/usr/bin/env bash
# Generate Airflow credentials once: append them to .env and write the auth manager passwords file.
set -euo pipefail

passwords_file="airflow/simple_auth_manager_passwords.json"

if grep -q "^AIRFLOW_AGENT_PASSWORD=" .env 2>/dev/null; then
    echo "Airflow secrets already exist in .env; nothing changed"
    exit 0
fi

admin_password=$(openssl rand -hex 12)
agent_password=$(openssl rand -hex 16)

cat >> .env << ENVEOF
AIRFLOW_UID=$(id -u)
AIRFLOW_POSTGRES_PASSWORD=$(openssl rand -hex 16)
AIRFLOW_JWT_SECRET=$(openssl rand -hex 32)
AIRFLOW_API_URL=http://localhost:8080
AIRFLOW_ADMIN_PASSWORD=${admin_password}
AIRFLOW_AGENT_USERNAME=mlops_agent
AIRFLOW_AGENT_PASSWORD=${agent_password}
ENVEOF

mkdir -p airflow
printf '{"admin": "%s", "mlops_agent": "%s"}\n' "${admin_password}" "${agent_password}" > "${passwords_file}"
chmod 600 "${passwords_file}"
echo "Airflow secrets written to .env and ${passwords_file}"
