"""Kubernetes operations tools, restricted to one approved namespace."""

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from agent.tools.errors import (
    ConfirmationRequiredError,
    InvalidToolInputError,
    ServiceUnavailableError,
    ToolPermissionError,
)

DEFAULT_NAMESPACE = "mlops-app"
DEFAULT_KUBECONFIG_PATH = ".kube/mlops-agent.kubeconfig"
DEFAULT_DEPLOYMENT_NAME = "adult-income-api"
DEFAULT_SERVICE_PORT_NAME = "http"
REQUEST_TIMEOUT_SECONDS = 10
MAXIMUM_LOG_LINES = 200
MAXIMUM_EVENTS = 20
RESOURCE_NAME_REGEX = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
PROBLEM_WAITING_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "InvalidImageName",
    "RunContainerError",
}
RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"

ReturnType = TypeVar("ReturnType")


def validate_resource_name(resource_name: str, field_name: str) -> str:
    if not RESOURCE_NAME_REGEX.match(resource_name):
        raise InvalidToolInputError(f"Invalid {field_name}: {resource_name!r}")
    return resource_name


def format_timestamp(timestamp: datetime | None) -> str | None:
    return timestamp.isoformat() if timestamp else None


def image_tag(image: str) -> str:
    return image.rsplit(":", 1)[1] if ":" in image.rsplit("/", 1)[-1] else "latest"


def describe_container_state(container_state: Any) -> dict[str, Any]:
    if container_state is None:
        return {"state": "unknown"}
    if container_state.waiting:
        return {
            "state": "waiting",
            "reason": container_state.waiting.reason,
            "message": container_state.waiting.message,
        }
    if container_state.terminated:
        return {
            "state": "terminated",
            "reason": container_state.terminated.reason,
            "exit_code": container_state.terminated.exit_code,
            "message": container_state.terminated.message,
        }
    if container_state.running:
        return {
            "state": "running",
            "started_at": format_timestamp(container_state.running.started_at),
        }
    return {"state": "unknown"}


def summarize_pod(pod: Any) -> dict[str, Any]:
    container_statuses = pod.status.container_statuses or []
    ready_condition = next(
        (condition for condition in pod.status.conditions or [] if condition.type == "Ready"), None
    )
    return {
        "name": pod.metadata.name,
        "phase": pod.status.phase,
        "ready": bool(ready_condition and ready_condition.status == "True"),
        "restart_count": sum(status.restart_count for status in container_statuses),
        "node": pod.spec.node_name if pod.spec else None,
        "images": [status.image for status in container_statuses],
        "created_at": format_timestamp(pod.metadata.creation_timestamp),
        "containers": [
            {
                "name": status.name,
                "ready": status.ready,
                "restart_count": status.restart_count,
                "current": describe_container_state(status.state),
                "previous": describe_container_state(status.last_state)
                if status.last_state and (status.last_state.terminated or status.last_state.waiting)
                else None,
            }
            for status in container_statuses
        ],
    }


def summarize_event(event: Any) -> dict[str, Any]:
    return {
        "type": event.type,
        "reason": event.reason,
        "object": f"{event.involved_object.kind}/{event.involved_object.name}",
        "message": event.message,
        "count": event.count,
        "last_seen": format_timestamp(event.last_timestamp or event.event_time),
    }


def identify_pod_problems(pod_summary: dict[str, Any]) -> list[str]:
    problems = []
    if not pod_summary["ready"]:
        problems.append("pod is not Ready")
    if pod_summary["restart_count"] > 0:
        problems.append(f"containers restarted {pod_summary['restart_count']} time(s)")
    for container in pod_summary["containers"]:
        current_state = container["current"]
        if current_state.get("reason") in PROBLEM_WAITING_REASONS:
            problems.append(f"{container['name']}: {current_state['reason']}")
        previous_state = container["previous"] or {}
        if previous_state.get("reason") == "OOMKilled":
            problems.append(f"{container['name']}: previously OOMKilled (memory limit exceeded)")
        elif previous_state.get("state") == "terminated" and previous_state.get("exit_code"):
            problems.append(
                f"{container['name']}: previous run exited with code {previous_state['exit_code']}"
            )
    if pod_summary["phase"] in {"Pending", "Failed", "Unknown"}:
        problems.append(f"pod phase is {pod_summary['phase']}")
    return problems


class KubernetesTools:
    def __init__(
        self,
        core_api: Any,
        apps_api: Any,
        discovery_api: Any,
        allowed_namespace: str = DEFAULT_NAMESPACE,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.core_api = core_api
        self.apps_api = apps_api
        self.discovery_api = discovery_api
        self.allowed_namespace = allowed_namespace
        self.clock = clock

    def list_workloads(self, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
        namespace = self._check_namespace(namespace)
        deployments = self._call(self.apps_api.list_namespaced_deployment, namespace).items
        pods = self._call(self.core_api.list_namespaced_pod, namespace).items
        return {
            "namespace": namespace,
            "deployments": [self._summarize_deployment(deployment) for deployment in deployments],
            "pods": [
                {key: value for key, value in summarize_pod(pod).items() if key != "containers"}
                for pod in pods
            ],
        }

    def get_pod_details(
        self, pod_name: str, namespace: str = DEFAULT_NAMESPACE, log_lines: int = 50
    ) -> dict[str, Any]:
        namespace = self._check_namespace(namespace)
        validate_resource_name(pod_name, "pod name")
        if not 1 <= log_lines <= MAXIMUM_LOG_LINES:
            raise InvalidToolInputError(f"log_lines must be between 1 and {MAXIMUM_LOG_LINES}")

        pod = self._call(self.core_api.read_namespaced_pod, pod_name, namespace)
        pod_summary = summarize_pod(pod)
        events = self._call(
            self.core_api.list_namespaced_event,
            namespace,
            field_selector=f"involvedObject.name={pod_name}",
        ).items
        return {
            **pod_summary,
            "conditions": [
                {"type": condition.type, "status": condition.status, "reason": condition.reason}
                for condition in pod.status.conditions or []
            ],
            "problems": identify_pod_problems(pod_summary),
            "events": [summarize_event(event) for event in events][-MAXIMUM_EVENTS:],
            "current_logs": self._read_logs(pod_name, namespace, log_lines, previous=False),
            "previous_logs": self._read_logs(pod_name, namespace, log_lines, previous=True)
            if pod_summary["restart_count"] > 0
            else None,
        }

    def inspect_services(self, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
        namespace = self._check_namespace(namespace)
        services = self._call(self.core_api.list_namespaced_service, namespace).items
        service_summaries = []
        for service in services:
            endpoint_slices = self._call(
                self.discovery_api.list_namespaced_endpoint_slice,
                namespace,
                label_selector=f"kubernetes.io/service-name={service.metadata.name}",
            ).items
            ready_endpoint_count = sum(
                1
                for endpoint_slice in endpoint_slices
                for endpoint in endpoint_slice.endpoints or []
                if endpoint.conditions and endpoint.conditions.ready
            )
            service_summaries.append(
                {
                    "name": service.metadata.name,
                    "type": service.spec.type,
                    "cluster_ip": service.spec.cluster_ip,
                    "selector": service.spec.selector,
                    "ports": [
                        {
                            "name": port.name,
                            "port": port.port,
                            "target_port": str(port.target_port),
                            "protocol": port.protocol,
                        }
                        for port in service.spec.ports or []
                    ],
                    "ready_endpoints": ready_endpoint_count,
                    "has_ready_endpoints": ready_endpoint_count > 0,
                }
            )
        return {"namespace": namespace, "services": service_summaries}

    def find_unhealthy_pods(self, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
        namespace = self._check_namespace(namespace)
        pods = self._call(self.core_api.list_namespaced_pod, namespace).items
        unhealthy_pods = []
        for pod in pods:
            pod_summary = summarize_pod(pod)
            problems = identify_pod_problems(pod_summary)
            if problems:
                unhealthy_pods.append(
                    {
                        "name": pod_summary["name"],
                        "phase": pod_summary["phase"],
                        "problems": problems,
                    }
                )
        warning_events = self._call(
            self.core_api.list_namespaced_event, namespace, field_selector="type=Warning"
        ).items
        return {
            "namespace": namespace,
            "total_pods": len(pods),
            "unhealthy_pods": unhealthy_pods,
            "all_healthy": not unhealthy_pods,
            "recent_warning_events": [summarize_event(event) for event in warning_events][
                -MAXIMUM_EVENTS:
            ],
        }

    def get_deployed_version(
        self, deployment_name: str = DEFAULT_DEPLOYMENT_NAME, namespace: str = DEFAULT_NAMESPACE
    ) -> dict[str, Any]:
        namespace = self._check_namespace(namespace)
        validate_resource_name(deployment_name, "deployment name")
        deployment = self._call(
            self.apps_api.read_namespaced_deployment, deployment_name, namespace
        )
        desired_images = [container.image for container in deployment.spec.template.spec.containers]
        pods = self._call(
            self.core_api.list_namespaced_pod,
            namespace,
            label_selector=",".join(
                f"{key}={value}" for key, value in deployment.spec.selector.match_labels.items()
            ),
        ).items
        running_images = sorted(
            {
                status.image
                for pod in pods
                for status in pod.status.container_statuses or []
                if status.ready
            }
        )
        return {
            "deployment": deployment_name,
            "desired_images": desired_images,
            "desired_image_tags": [image_tag(image) for image in desired_images],
            "running_ready_images": running_images,
            "rollout_complete": running_images == sorted(set(desired_images)),
            "service_reported_version": self._read_version_endpoint(deployment_name, namespace),
        }

    def restart_deployment(
        self,
        deployment_name: str,
        namespace: str = DEFAULT_NAMESPACE,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        namespace = self._check_namespace(namespace)
        validate_resource_name(deployment_name, "deployment name")
        if not confirmed:
            raise ConfirmationRequiredError(
                f"restart all pods of deployment {deployment_name!r} in namespace {namespace!r}"
            )
        restart_time = self.clock().isoformat()
        patch_body = {
            "spec": {"template": {"metadata": {"annotations": {RESTART_ANNOTATION: restart_time}}}}
        }
        self._call(
            self.apps_api.patch_namespaced_deployment, deployment_name, namespace, patch_body
        )
        return {
            "deployment": deployment_name,
            "namespace": namespace,
            "restarted_at": restart_time,
            "note": "A rolling restart was started; pods are replaced one at a time.",
        }

    def _check_namespace(self, namespace: str) -> str:
        if namespace != self.allowed_namespace:
            raise ToolPermissionError(
                f"Namespace {namespace!r} is not approved. "
                f"The agent may only operate in {self.allowed_namespace!r}."
            )
        return namespace

    def _summarize_deployment(self, deployment: Any) -> dict[str, Any]:
        status = deployment.status
        return {
            "name": deployment.metadata.name,
            "desired_replicas": deployment.spec.replicas,
            "ready_replicas": status.ready_replicas or 0,
            "available_replicas": status.available_replicas or 0,
            "updated_replicas": status.updated_replicas or 0,
            "images": [container.image for container in deployment.spec.template.spec.containers],
        }

    def _read_logs(
        self, pod_name: str, namespace: str, log_lines: int, previous: bool
    ) -> list[str] | str:
        try:
            log_text = self._call(
                self.core_api.read_namespaced_pod_log,
                pod_name,
                namespace,
                tail_lines=log_lines,
                previous=previous,
            )
        except (InvalidToolInputError, ServiceUnavailableError) as error:
            return f"Logs unavailable: {error}"
        return log_text.splitlines()

    def _read_version_endpoint(self, service_name: str, namespace: str) -> dict[str, Any]:
        try:
            response = self._call(
                self.core_api.connect_get_namespaced_service_proxy_with_path,
                f"{service_name}:{DEFAULT_SERVICE_PORT_NAME}",
                namespace,
                "version",
                _preload_content=False,
            )
            return {"available": True, **json.loads(response.data)}
        except (
            InvalidToolInputError,
            ServiceUnavailableError,
            ToolPermissionError,
            ValueError,
        ) as error:
            return {"available": False, "reason": str(error)}

    @staticmethod
    def _call(
        function: Callable[..., ReturnType], *arguments: Any, **keyword_arguments: Any
    ) -> ReturnType:
        keyword_arguments.setdefault("_request_timeout", REQUEST_TIMEOUT_SECONDS)
        try:
            return function(*arguments, **keyword_arguments)
        except ApiException as error:
            if error.status == 404:
                raise InvalidToolInputError(
                    f"Kubernetes resource not found: {error.reason}"
                ) from error
            if error.status == 403:
                raise ToolPermissionError(
                    f"Kubernetes RBAC denied the request: {error.reason}"
                ) from error
            if error.status == 400:
                raise InvalidToolInputError(
                    f"Kubernetes rejected the request: {error.body}"
                ) from error
            raise ServiceUnavailableError(
                f"Kubernetes API returned {error.status}: {error.reason}"
            ) from error
        except (Urllib3HTTPError, OSError) as error:
            raise ServiceUnavailableError(f"Kubernetes API is unreachable: {error}") from error


def create_kubernetes_tools() -> KubernetesTools:
    kubeconfig_path = Path(os.environ.get("AGENT_KUBECONFIG", DEFAULT_KUBECONFIG_PATH))
    if not kubeconfig_path.exists():
        raise ServiceUnavailableError(
            f"Agent kubeconfig not found at {kubeconfig_path}. "
            "Run scripts/create_agent_kubeconfig.sh first."
        )
    api_client = config.new_client_from_config(config_file=str(kubeconfig_path))
    return KubernetesTools(
        core_api=client.CoreV1Api(api_client),
        apps_api=client.AppsV1Api(api_client),
        discovery_api=client.DiscoveryV1Api(api_client),
        allowed_namespace=os.environ.get("AGENT_KUBERNETES_NAMESPACE", DEFAULT_NAMESPACE),
    )
