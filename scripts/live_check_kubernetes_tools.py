"""Run the Kubernetes tools against the kind cluster and prove both safety layers hold."""

import sys
from pathlib import Path

import yaml
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from agent.tools.errors import ConfirmationRequiredError, ToolPermissionError
from agent.tools.kubernetes_tools import DEFAULT_KUBECONFIG_PATH, create_kubernetes_tools

NAMESPACE = "mlops-app"
DEPLOYMENT_NAME = "adult-income-api"
EXPECTED_REPLICAS = 2


def expect_rbac_denial(description: str, api_call) -> None:
    try:
        api_call()
    except ApiException as error:
        assert error.status == 403, f"{description}: expected 403, got {error.status}"
        return
    raise AssertionError(f"{description}: RBAC allowed a request it should deny")


def main() -> int:
    kubernetes_tools = create_kubernetes_tools()

    workloads = kubernetes_tools.list_workloads(NAMESPACE)
    deployment = next(item for item in workloads["deployments"] if item["name"] == DEPLOYMENT_NAME)
    assert deployment["ready_replicas"] == EXPECTED_REPLICAS, f"Deployment: {deployment}"

    health = kubernetes_tools.find_unhealthy_pods(NAMESPACE)
    assert health["all_healthy"], f"Unhealthy pods: {health['unhealthy_pods']}"

    service = kubernetes_tools.inspect_services(NAMESPACE)["services"][0]
    assert service["type"] == "ClusterIP" and service["ready_endpoints"] == EXPECTED_REPLICAS

    deployed_version = kubernetes_tools.get_deployed_version(DEPLOYMENT_NAME, NAMESPACE)
    reported = deployed_version["service_reported_version"]
    assert reported["available"], f"/version not reachable: {reported}"
    expected_tag = f"model-v{reported['model']['model_version']}"
    assert deployed_version["desired_image_tags"] == [expected_tag], deployed_version

    # Safety layer 1: the tool code refuses other namespaces and unconfirmed changes
    for blocked_call in (
        lambda: kubernetes_tools.list_workloads("kube-system"),
        lambda: kubernetes_tools.restart_deployment(DEPLOYMENT_NAME, NAMESPACE),
    ):
        try:
            blocked_call()
        except (ToolPermissionError, ConfirmationRequiredError):
            pass
        else:
            raise AssertionError("Tool allowed an operation it should block")

    # Safety layer 2: even bypassing the tool code, RBAC denies the agent's credentials
    raw_api_client = config.new_client_from_config(config_file=DEFAULT_KUBECONFIG_PATH)
    core_api = client.CoreV1Api(raw_api_client)
    apps_api = client.AppsV1Api(raw_api_client)
    expect_rbac_denial(
        "list pods in kube-system", lambda: core_api.list_namespaced_pod("kube-system")
    )
    expect_rbac_denial(
        "delete the API deployment",
        lambda: apps_api.delete_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE),
    )
    expect_rbac_denial("read secrets", lambda: core_api.list_namespaced_secret(NAMESPACE))

    kubeconfig_user = yaml.safe_load(Path(DEFAULT_KUBECONFIG_PATH).read_text())["users"][0]["name"]
    print(
        f"{DEPLOYMENT_NAME} running {expected_tag} with {EXPECTED_REPLICAS} ready pods; "
        f"RBAC for '{kubeconfig_user}' denies kube-system, deletes and secrets"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
