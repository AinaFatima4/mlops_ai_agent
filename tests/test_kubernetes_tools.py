import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from kubernetes.client import (
    CoreV1Event,
    V1Container,
    V1ContainerState,
    V1ContainerStateRunning,
    V1ContainerStateTerminated,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1Deployment,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1LabelSelector,
    V1ObjectMeta,
    V1ObjectReference,
    V1Pod,
    V1PodCondition,
    V1PodSpec,
    V1PodStatus,
    V1PodTemplateSpec,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import MaxRetryError

from agent.tools.errors import (
    ConfirmationRequiredError,
    InvalidToolInputError,
    ServiceUnavailableError,
    ToolPermissionError,
)
from agent.tools.kubernetes_tools import KubernetesTools

NAMESPACE = "mlops-app"
DEPLOYMENT_NAME = "adult-income-api"
IMAGE = "adult-income-api:model-v3"
FIXED_TIME = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def build_pod(
    name: str,
    ready: bool = True,
    restart_count: int = 0,
    waiting_reason: str | None = None,
    previous_termination_reason: str | None = None,
) -> V1Pod:
    current_state = (
        V1ContainerState(waiting=V1ContainerStateWaiting(reason=waiting_reason, message="details"))
        if waiting_reason
        else V1ContainerState(running=V1ContainerStateRunning(started_at=FIXED_TIME))
    )
    previous_state = (
        V1ContainerState(
            terminated=V1ContainerStateTerminated(reason=previous_termination_reason, exit_code=137)
        )
        if previous_termination_reason
        else V1ContainerState()
    )
    return V1Pod(
        metadata=V1ObjectMeta(name=name, namespace=NAMESPACE, creation_timestamp=FIXED_TIME),
        spec=V1PodSpec(containers=[V1Container(name="api", image=IMAGE)], node_name="mlops-node"),
        status=V1PodStatus(
            phase="Running",
            conditions=[V1PodCondition(type="Ready", status="True" if ready else "False")],
            container_statuses=[
                V1ContainerStatus(
                    name="api",
                    image=IMAGE,
                    image_id="",
                    ready=ready,
                    restart_count=restart_count,
                    state=current_state,
                    last_state=previous_state,
                )
            ],
        ),
    )


def build_deployment() -> V1Deployment:
    return V1Deployment(
        metadata=V1ObjectMeta(name=DEPLOYMENT_NAME, namespace=NAMESPACE),
        spec=V1DeploymentSpec(
            replicas=2,
            selector=V1LabelSelector(match_labels={"app.kubernetes.io/name": DEPLOYMENT_NAME}),
            template=V1PodTemplateSpec(
                spec=V1PodSpec(containers=[V1Container(name="api", image=IMAGE)])
            ),
        ),
        status=V1DeploymentStatus(ready_replicas=2, available_replicas=2, updated_replicas=2),
    )


def build_warning_event(object_name: str, reason: str, message: str) -> CoreV1Event:
    return CoreV1Event(
        metadata=V1ObjectMeta(name=f"{object_name}.event"),
        involved_object=V1ObjectReference(kind="Pod", name=object_name),
        type="Warning",
        reason=reason,
        message=message,
        count=4,
        last_timestamp=FIXED_TIME,
    )


class FakeCoreApi:
    def __init__(self, pods: list[V1Pod], events: list[CoreV1Event] | None = None) -> None:
        self.pods = pods
        self.events = events or []
        self.calls: list[str] = []
        self.version_response: object = SimpleNamespace(
            data=json.dumps({"app_version": "1.0.0", "model": {"model_version": "3"}}).encode()
        )

    def list_namespaced_pod(self, namespace: str, **options: object) -> SimpleNamespace:
        self.calls.append("list_namespaced_pod")
        return SimpleNamespace(items=self.pods)

    def read_namespaced_pod(self, name: str, namespace: str, **options: object) -> V1Pod:
        self.calls.append("read_namespaced_pod")
        for pod in self.pods:
            if pod.metadata.name == name:
                return pod
        raise ApiException(status=404, reason="Not Found")

    def list_namespaced_event(self, namespace: str, **options: object) -> SimpleNamespace:
        self.calls.append("list_namespaced_event")
        return SimpleNamespace(items=self.events)

    def read_namespaced_pod_log(
        self, name: str, namespace: str, previous: bool = False, **options: object
    ) -> str:
        self.calls.append(f"read_log_previous={previous}")
        if previous:
            return "ERROR Model failed to load\nTraceback: FileNotFoundError"
        return "INFO starting\nINFO ready"

    def list_namespaced_service(self, namespace: str, **options: object) -> SimpleNamespace:
        service = V1Service(
            metadata=V1ObjectMeta(name=DEPLOYMENT_NAME),
            spec=V1ServiceSpec(
                type="ClusterIP",
                cluster_ip="10.96.0.20",
                selector={"app.kubernetes.io/name": DEPLOYMENT_NAME},
                ports=[V1ServicePort(name="http", port=80, target_port="http", protocol="TCP")],
            ),
        )
        return SimpleNamespace(items=[service])

    def connect_get_namespaced_service_proxy_with_path(
        self, name: str, namespace: str, path: str, **options: object
    ) -> object:
        if isinstance(self.version_response, Exception):
            raise self.version_response
        return self.version_response


class FakeAppsApi:
    def __init__(self) -> None:
        self.patches: list[dict] = []

    def list_namespaced_deployment(self, namespace: str, **options: object) -> SimpleNamespace:
        return SimpleNamespace(items=[build_deployment()])

    def read_namespaced_deployment(self, name: str, namespace: str, **options: object):
        return build_deployment()

    def patch_namespaced_deployment(
        self, name: str, namespace: str, body: dict, **options: object
    ) -> V1Deployment:
        self.patches.append(body)
        return build_deployment()


class FakeDiscoveryApi:
    def __init__(self, ready_endpoint_count: int) -> None:
        self.ready_endpoint_count = ready_endpoint_count

    def list_namespaced_endpoint_slice(self, namespace: str, **options: object) -> SimpleNamespace:
        endpoints = [
            SimpleNamespace(conditions=SimpleNamespace(ready=True))
            for _ in range(self.ready_endpoint_count)
        ]
        return SimpleNamespace(items=[SimpleNamespace(endpoints=endpoints)])


def build_tools(
    pods: list[V1Pod],
    events: list[CoreV1Event] | None = None,
    ready_endpoint_count: int = 2,
) -> tuple[KubernetesTools, FakeCoreApi, FakeAppsApi]:
    core_api = FakeCoreApi(pods, events)
    apps_api = FakeAppsApi()
    tools = KubernetesTools(
        core_api, apps_api, FakeDiscoveryApi(ready_endpoint_count), clock=lambda: FIXED_TIME
    )
    return tools, core_api, apps_api


@pytest.mark.parametrize(
    "tool_call",
    [
        lambda tools: tools.list_workloads("kube-system"),
        lambda tools: tools.find_unhealthy_pods("default"),
        lambda tools: tools.inspect_services("kube-system"),
        lambda tools: tools.get_pod_details("coredns", "kube-system"),
        lambda tools: tools.restart_deployment("coredns", "kube-system", confirmed=True),
    ],
)
def test_other_namespaces_are_rejected_before_any_api_call(tool_call) -> None:
    tools, core_api, apps_api = build_tools([build_pod("api-1")])
    with pytest.raises(ToolPermissionError):
        tool_call(tools)
    assert core_api.calls == []
    assert apps_api.patches == []


def test_restart_without_confirmation_changes_nothing() -> None:
    tools, _, apps_api = build_tools([build_pod("api-1")])
    with pytest.raises(ConfirmationRequiredError):
        tools.restart_deployment(DEPLOYMENT_NAME, NAMESPACE)
    assert apps_api.patches == []


def test_confirmed_restart_patches_restart_annotation() -> None:
    tools, _, apps_api = build_tools([build_pod("api-1")])
    result = tools.restart_deployment(DEPLOYMENT_NAME, NAMESPACE, confirmed=True)
    annotations = apps_api.patches[0]["spec"]["template"]["metadata"]["annotations"]
    assert annotations["kubectl.kubernetes.io/restartedAt"] == FIXED_TIME.isoformat()
    assert result["restarted_at"] == FIXED_TIME.isoformat()


def test_unhealthy_pods_report_crash_loop_and_oom_kill() -> None:
    pods = [
        build_pod("api-healthy"),
        build_pod("api-crashing", ready=False, restart_count=5, waiting_reason="CrashLoopBackOff"),
        build_pod("api-oom", restart_count=1, previous_termination_reason="OOMKilled"),
    ]
    events = [
        build_warning_event("api-crashing", "BackOff", "Back-off restarting failed container")
    ]
    tools, _, _ = build_tools(pods, events)
    result = tools.find_unhealthy_pods(NAMESPACE)
    problems_by_pod = {pod["name"]: pod["problems"] for pod in result["unhealthy_pods"]}
    assert set(problems_by_pod) == {"api-crashing", "api-oom"}
    assert "api: CrashLoopBackOff" in problems_by_pod["api-crashing"]
    assert any("OOMKilled" in problem for problem in problems_by_pod["api-oom"])
    assert result["recent_warning_events"][0]["reason"] == "BackOff"
    assert result["all_healthy"] is False


def test_healthy_namespace_reports_all_healthy() -> None:
    tools, _, _ = build_tools([build_pod("api-1"), build_pod("api-2")])
    assert tools.find_unhealthy_pods(NAMESPACE)["all_healthy"] is True


def test_pod_details_include_previous_logs_after_restart() -> None:
    tools, core_api, _ = build_tools(
        [build_pod("api-1", ready=False, restart_count=2, waiting_reason="CrashLoopBackOff")]
    )
    result = tools.get_pod_details("api-1", NAMESPACE)
    assert "read_log_previous=True" in core_api.calls
    assert result["previous_logs"][0] == "ERROR Model failed to load"
    assert result["containers"][0]["current"]["reason"] == "CrashLoopBackOff"


def test_service_without_ready_endpoints_is_flagged() -> None:
    tools, _, _ = build_tools([build_pod("api-1", ready=False)], ready_endpoint_count=0)
    service = tools.inspect_services(NAMESPACE)["services"][0]
    assert service["ready_endpoints"] == 0
    assert service["has_ready_endpoints"] is False


def test_deployed_version_combines_image_tag_and_version_endpoint() -> None:
    tools, _, _ = build_tools([build_pod("api-1"), build_pod("api-2")])
    result = tools.get_deployed_version(DEPLOYMENT_NAME, NAMESPACE)
    assert result["desired_image_tags"] == ["model-v3"]
    assert result["rollout_complete"] is True
    assert result["service_reported_version"]["model"]["model_version"] == "3"


def test_unreachable_version_endpoint_is_reported_not_invented() -> None:
    tools, core_api, _ = build_tools([build_pod("api-1")])
    core_api.version_response = ApiException(status=503, reason="Service Unavailable")
    result = tools.get_deployed_version(DEPLOYMENT_NAME, NAMESPACE)
    assert result["service_reported_version"]["available"] is False


def test_unknown_pod_raises_invalid_input() -> None:
    tools, _, _ = build_tools([build_pod("api-1")])
    with pytest.raises(InvalidToolInputError):
        tools.get_pod_details("api-missing", NAMESPACE)


def test_rbac_denial_becomes_permission_error() -> None:
    tools, core_api, _ = build_tools([])

    def deny(*arguments: object, **options: object) -> None:
        raise ApiException(status=403, reason="Forbidden")

    core_api.list_namespaced_pod = deny
    with pytest.raises(ToolPermissionError):
        tools.find_unhealthy_pods(NAMESPACE)


def test_unreachable_cluster_becomes_service_unavailable() -> None:
    tools, core_api, _ = build_tools([])

    def refuse(*arguments: object, **options: object) -> None:
        raise MaxRetryError(pool=None, url="/api/v1/pods", reason="connection refused")

    core_api.list_namespaced_pod = refuse
    with pytest.raises(ServiceUnavailableError):
        tools.find_unhealthy_pods(NAMESPACE)


@pytest.mark.parametrize("pod_name", ["../secrets", "API-UPPER", "pod;rm", ""])
def test_malformed_resource_names_are_rejected(pod_name: str) -> None:
    tools, core_api, _ = build_tools([])
    with pytest.raises(InvalidToolInputError):
        tools.get_pod_details(pod_name, NAMESPACE)
    assert core_api.calls == []
