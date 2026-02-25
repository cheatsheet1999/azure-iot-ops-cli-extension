# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import json
from typing import Optional

import pytest
import responses
from azure.cli.core.azclierror import InvalidArgumentValueError, ValidationError

from azext_edge.edge.providers.orchestration.common import (
    MANAGED_IDENTITY_API_VERSION,
    MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
    MGMT_ACTIONS_DEFAULT_DATAFLOW_PROFILE,
    MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP,
    MGMT_ACTIONS_DEFAULT_MQTT_ENDPOINT,
    MGMT_ACTIONS_DEFAULT_REGISTRY_ENDPOINT,
    MGMT_ACTIONS_EG_AUDIENCE,
    MGMT_ACTIONS_GRAPH_ARTIFACT,
    MGMT_ACTIONS_GRAPH_RULES_VERSION,
    MGMT_ACTIONS_REQUEST_TOPIC_TEMPLATE,
    MGMT_ACTIONS_RESPONSE_TOPIC_TEMPLATE,
    MIN_INSTANCE_VERSION_MGMT_ACTIONS,
    MQTT_ENDPOINT_TYPE,
)
from azext_edge.edge.util.az_client import (
    DEFAULT_DEVICEREGISTRY_MGMT_API_VERSION,
    DEFAULT_EVENTGRID_MGMT_API_VERSION,
    DEFAULT_IOTOPS_MGMT_API_VERSION,
)
from azext_edge.edge.providers.orchestration.mgmt_actions import (
    EgNamespaceContext,
    MgmtActions,
    _build_graph_rules_config,
    get_mgmt_actions_resource_name,
)

from ...generators import BASE_URL, generate_random_string, generate_resource_id, get_zeroed_subscription

ZEROED_SUBSCRIPTION = get_zeroed_subscription()
DEVICEREGISTRY_RP = "Microsoft.DeviceRegistry"
DEVICEREGISTRY_API_VERSION = DEFAULT_DEVICEREGISTRY_MGMT_API_VERSION.value
EVENTGRID_RP = "Microsoft.EventGrid"
EVENTGRID_API_VERSION = DEFAULT_EVENTGRID_MGMT_API_VERSION.value
IOTOPS_RP = "Microsoft.IoTOperations"
IOTOPS_API_VERSION = DEFAULT_IOTOPS_MGMT_API_VERSION.value
UAMI_API_VERSION = MANAGED_IDENTITY_API_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_eg_resource_id(
    namespace_name: str,
    resource_group_name: str,
    subscription_id: Optional[str] = None,
) -> str:
    return generate_resource_id(
        resource_group_name=resource_group_name,
        resource_provider=EVENTGRID_RP,
        resource_path=f"/namespaces/{namespace_name}",
        resource_subscription=subscription_id,
    )


def _build_eg_endpoint(
    namespace_name: str,
    resource_group_name: str,
    subscription_id: Optional[str] = None,
    sub_resource: Optional[str] = None,
) -> str:
    """Build a full management endpoint URL for an EG namespace or sub-resource."""
    sub_id = subscription_id or ZEROED_SUBSCRIPTION
    url = (
        f"{BASE_URL}/subscriptions/{sub_id}/resourceGroups/{resource_group_name}"
        f"/providers/{EVENTGRID_RP}/namespaces/{namespace_name}"
    )
    if sub_resource:
        url += sub_resource
    url += f"?api-version={EVENTGRID_API_VERSION}"
    return url


def _build_iotops_endpoint(
    instance_name: str,
    resource_group_name: str,
    sub_resource: Optional[str] = None,
) -> str:
    """Build a full management endpoint URL for an IoT Operations instance or sub-resource."""
    url = (
        f"{BASE_URL}/subscriptions/{ZEROED_SUBSCRIPTION}/resourceGroups/{resource_group_name}"
        f"/providers/{IOTOPS_RP}/instances/{instance_name}"
    )
    if sub_resource:
        url += sub_resource
    url += f"?api-version={IOTOPS_API_VERSION}"
    return url


def _build_uami_endpoint(mi_resource_id: str) -> str:
    """Build a full management endpoint URL for a user-assigned managed identity GET."""
    return f"{BASE_URL}{mi_resource_id}?api-version={UAMI_API_VERSION}"


def _build_uami_resource_id(
    identity_name: str,
    resource_group_name: str,
    subscription_id: Optional[str] = None,
) -> str:
    sub_id = subscription_id or ZEROED_SUBSCRIPTION
    return (
        f"/subscriptions/{sub_id}/resourceGroups/{resource_group_name}"
        f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{identity_name}"
    )


def _build_uami_response(
    mi_resource_id: str,
    client_id: str,
    tenant_id: str,
) -> dict:
    return {
        "id": mi_resource_id,
        "properties": {
            "clientId": client_id,
            "tenantId": tenant_id,
            "principalId": "00000000-0000-0000-0000-aaaaaaaaaaaa",
        },
    }


def _build_namespace_response(
    namespace_name: str,
    resource_group_name: str,
    topic_spaces_state: str = "Enabled",
    mqtt_hostname: str = "test-ns.eastus-1.ts.eventgrid.azure.net",
    subscription_id: Optional[str] = None,
) -> dict:
    sub_id = subscription_id or ZEROED_SUBSCRIPTION
    return {
        "id": (
            f"/subscriptions/{sub_id}/resourceGroups/{resource_group_name}"
            f"/providers/{EVENTGRID_RP}/namespaces/{namespace_name}"
        ),
        "name": namespace_name,
        "location": "eastus",
        "properties": {
            "provisioningState": "Succeeded",
            "topicSpacesConfiguration": {
                "state": topic_spaces_state,
                "hostname": mqtt_hostname,
            },
        },
    }


def _build_topic_space_response(
    topic_space_name: str,
    topic_templates: list,
    description: str = "",
) -> dict:
    return {
        "id": f"/fake/path/topicSpaces/{topic_space_name}",
        "name": topic_space_name,
        "properties": {
            "description": description,
            "provisioningState": "Succeeded",
            "topicTemplates": topic_templates,
        },
    }


def _build_permission_binding_response(
    binding_name: str,
    permission: str,
    topic_space_name: str,
    client_group_name: str = "$all",
) -> dict:
    return {
        "id": f"/fake/path/permissionBindings/{binding_name}",
        "name": binding_name,
        "properties": {
            "clientGroupName": client_group_name,
            "permission": permission,
            "topicSpaceName": topic_space_name,
            "provisioningState": "Succeeded",
            "description": "",
        },
    }


def _get_expected_topic_templates(instance_name: str) -> list:
    return [
        MGMT_ACTIONS_REQUEST_TOPIC_TEMPLATE.format(scope_id=instance_name),
        MGMT_ACTIONS_RESPONSE_TOPIC_TEMPLATE.format(scope_id=instance_name),
    ]


def _build_adr_namespace_resource_id(
    namespace_name: str,
    resource_group_name: str,
    subscription_id: Optional[str] = None,
) -> str:
    return generate_resource_id(
        resource_group_name=resource_group_name,
        resource_provider=DEVICEREGISTRY_RP,
        resource_path=f"/namespaces/{namespace_name}",
        resource_subscription=subscription_id,
    )


def _build_adr_endpoint(
    namespace_name: str,
    resource_group_name: str,
    subscription_id: Optional[str] = None,
) -> str:
    """Build a full management endpoint URL for an ADR namespace."""
    sub_id = subscription_id or ZEROED_SUBSCRIPTION
    return (
        f"{BASE_URL}/subscriptions/{sub_id}/resourceGroups/{resource_group_name}"
        f"/providers/{DEVICEREGISTRY_RP}/namespaces/{namespace_name}"
        f"?api-version={DEVICEREGISTRY_API_VERSION}"
    )


def _build_adr_namespace_response(
    namespace_name: str,
    resource_group_name: str,
    identity_type: str = "None",
    principal_id: Optional[str] = None,
    management_endpoints: Optional[dict] = None,
    subscription_id: Optional[str] = None,
) -> dict:
    """Build a mock ADR namespace GET response."""
    sub_id = subscription_id or ZEROED_SUBSCRIPTION
    result: dict = {
        "id": (
            f"/subscriptions/{sub_id}/resourceGroups/{resource_group_name}"
            f"/providers/{DEVICEREGISTRY_RP}/namespaces/{namespace_name}"
        ),
        "name": namespace_name,
        "location": "eastus",
        "identity": {
            "type": identity_type,
        },
        "properties": {
            "provisioningState": "Succeeded",
        },
    }
    if principal_id:
        result["identity"]["principalId"] = principal_id
    if management_endpoints is not None:
        result["properties"]["management"] = {"endpoints": management_endpoints}
    return result


def _make_eg_ctx(
    namespace_name: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    mqtt_hostname: Optional[str] = None,
) -> EgNamespaceContext:
    ns = namespace_name or "test-ns"
    rg = resource_group_name or "test-rg"
    return EgNamespaceContext(
        resource_id=_build_eg_resource_id(ns, rg),
        subscription_id=ZEROED_SUBSCRIPTION,
        resource_group_name=rg,
        namespace_name=ns,
        mqtt_hostname=mqtt_hostname or "test-ns.eastus-1.ts.eventgrid.azure.net",
    )


def _make_extended_location() -> dict:
    return {
        "name": f"/subscriptions/{ZEROED_SUBSCRIPTION}/resourceGroups/test-rg"
        f"/providers/Microsoft.ExtendedLocation/customLocations/my-cl",
        "type": "CustomLocation",
    }


def _build_instance_response(
    instance_name: str,
    resource_group_name: str,
    version: str = MIN_INSTANCE_VERSION_MGMT_ACTIONS,
    adr_namespace_name: Optional[str] = None,
) -> dict:
    extended_location = _make_extended_location()
    adr_ns_name = adr_namespace_name or f"{instance_name}-adr-ns"
    adr_ns_rid = _build_adr_namespace_resource_id(adr_ns_name, resource_group_name)
    return {
        "id": (
            f"/subscriptions/{ZEROED_SUBSCRIPTION}/resourceGroups/{resource_group_name}"
            f"/providers/{IOTOPS_RP}/instances/{instance_name}"
        ),
        "name": instance_name,
        "location": "eastus",
        "extendedLocation": extended_location,
        "properties": {
            "version": version,
            "provisioningState": "Succeeded",
            "adrNamespaceRef": {"resourceId": adr_ns_rid},
        },
    }


# ---------------------------------------------------------------------------
# _validate_eg_namespace tests
# ---------------------------------------------------------------------------


class TestValidateEgNamespace:
    """Tests for MgmtActions._validate_eg_namespace()."""

    def test_happy_path(self, mocked_cmd, mocked_responses: responses):
        """Valid EG namespace with topic spaces enabled returns correct EgNamespaceContext."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        eg_resource_id = _build_eg_resource_id(ns_name, rg)
        hostname = "myns.eastus-1.ts.eventgrid.azure.net"

        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg),
            json=_build_namespace_response(ns_name, rg, mqtt_hostname=hostname),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        ctx = provider._validate_eg_namespace(eg_resource_id)

        assert isinstance(ctx, EgNamespaceContext)
        assert ctx.resource_id == eg_resource_id
        assert ctx.subscription_id == ZEROED_SUBSCRIPTION
        assert ctx.resource_group_name == rg
        assert ctx.namespace_name == ns_name
        assert ctx.mqtt_hostname == hostname
        assert len(mocked_responses.calls) == 1

    @pytest.mark.parametrize(
        "bad_resource_id",
        [
            # Wrong resource provider
            "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1",
            # Wrong resource type under EventGrid
            "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.EventGrid/topics/mytopic",
            # Completely malformed
            "/subscriptions/sub1/resourceGroups/rg1",
        ],
    )
    def test_invalid_resource_type(self, mocked_cmd, mocked_responses: responses, bad_resource_id: str):
        """Non-EventGrid/namespaces resource IDs raise InvalidArgumentValueError."""
        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(InvalidArgumentValueError, match="Microsoft.EventGrid/namespaces"):
            provider._validate_eg_namespace(bad_resource_id)
        # No HTTP calls should be made for format validation failures
        assert len(mocked_responses.calls) == 0

    def test_namespace_not_found(self, mocked_cmd, mocked_responses: responses):
        """404 from namespace GET raises InvalidArgumentValueError."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        eg_resource_id = _build_eg_resource_id(ns_name, rg)

        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(InvalidArgumentValueError, match="not found"):
            provider._validate_eg_namespace(eg_resource_id)

    @pytest.mark.parametrize(
        "state, expected_snippet",
        [
            ("Disabled", "Current state: 'Disabled'"),
            ("", "MQTT broker has not been configured"),
        ],
    )
    def test_topic_spaces_not_enabled(
        self,
        mocked_cmd,
        mocked_responses: responses,
        state: str,
        expected_snippet: str,
    ):
        """Namespace with topic spaces not enabled raises ValidationError with appropriate detail."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        eg_resource_id = _build_eg_resource_id(ns_name, rg)

        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg),
            json=_build_namespace_response(ns_name, rg, topic_spaces_state=state),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(ValidationError, match=expected_snippet):
            provider._validate_eg_namespace(eg_resource_id)

    def test_missing_mqtt_hostname(self, mocked_cmd, mocked_responses: responses):
        """Namespace with topic spaces enabled but no hostname raises ValidationError."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        eg_resource_id = _build_eg_resource_id(ns_name, rg)

        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg),
            json=_build_namespace_response(ns_name, rg, mqtt_hostname=""),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(ValidationError, match="no MQTT hostname"):
            provider._validate_eg_namespace(eg_resource_id)

    def test_cross_subscription(self, mocked_cmd, mocked_responses: responses):
        """EG namespace in a different subscription creates a cross-subscription client."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        cross_sub = "11111111-1111-1111-1111-111111111111"
        eg_resource_id = _build_eg_resource_id(ns_name, rg, subscription_id=cross_sub)
        hostname = "cross-sub.eastus-1.ts.eventgrid.azure.net"

        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, subscription_id=cross_sub),
            json=_build_namespace_response(ns_name, rg, mqtt_hostname=hostname, subscription_id=cross_sub),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        original_client = provider.eventgrid_mgmt_client
        ctx = provider._validate_eg_namespace(eg_resource_id)

        assert ctx.subscription_id == cross_sub
        assert ctx.mqtt_hostname == hostname
        # Client should have been replaced
        assert provider.eventgrid_mgmt_client is not original_client
        assert len(mocked_responses.calls) == 1


# ---------------------------------------------------------------------------
# _setup_eg_topic_space tests
# ---------------------------------------------------------------------------


class TestSetupEgTopicSpace:
    """Tests for MgmtActions._setup_eg_topic_space()."""

    def test_create_new_topic_space(self, mocked_cmd, mocked_responses: responses):
        """When topic space does not exist, creates it and returns status 'Created'."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)

        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        expected_templates = _get_expected_topic_templates(instance_name)

        # GET returns 404 (doesn't exist)
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # PUT creates it
        ts_response = _build_topic_space_response(ts_name, expected_templates)
        mocked_responses.add(
            method=responses.PUT,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json=ts_response,
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_topic_space(
            eg_ctx=eg_ctx,
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            wait_sec=0,
        )

        assert result["name"] == ts_name
        assert result["topicTemplates"] == expected_templates
        assert result["scopeId"] == instance_name
        assert len(mocked_responses.calls) == 2

        # Verify the PUT payload
        put_body = json.loads(mocked_responses.calls[1].request.body)
        assert put_body["properties"]["topicTemplates"] == expected_templates
        assert instance_name in put_body["properties"]["description"]

    def test_existing_topic_space(self, mocked_cmd, mocked_responses: responses):
        """When topic space already exists, returns status 'Exists' without PUT."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)

        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        expected_templates = _get_expected_topic_templates(instance_name)

        # GET returns 200 (already exists)
        ts_response = _build_topic_space_response(ts_name, expected_templates)
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json=ts_response,
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_topic_space(
            eg_ctx=eg_ctx,
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            wait_sec=0,
        )

        assert result["name"] == ts_name
        assert result["topicTemplates"] == expected_templates
        assert result["scopeId"] == instance_name
        # Only the GET call, no PUT
        assert len(mocked_responses.calls) == 1

    def test_deterministic_naming(self, mocked_cmd, mocked_responses: responses):
        """Topic space name is deterministic based on instance resource ID."""
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("some-instance", rg)

        name_a = get_mgmt_actions_resource_name("ops", instance_rid)
        name_b = get_mgmt_actions_resource_name("ops", instance_rid)
        assert name_a == name_b
        assert name_a.startswith("mgmt-actions-ops-")
        assert len(name_a) == 25  # "mgmt-actions-ops-" (17) + hash8 (8) = 25

    def test_topic_templates_use_instance_name_as_scope(self, mocked_cmd, mocked_responses: responses):
        """Topic templates substitute scope_id with the instance name."""
        instance_name = "my-iot-instance"
        templates = _get_expected_topic_templates(instance_name)
        assert templates[0] == f"actions/requests/{instance_name}/#"
        assert templates[1] == f"actions/responses/{instance_name}/#"


# ---------------------------------------------------------------------------
# _setup_eg_permission_bindings tests
# ---------------------------------------------------------------------------


class TestSetupEgPermissionBindings:
    """Tests for MgmtActions._setup_eg_permission_bindings()."""

    def test_create_both_bindings(self, mocked_cmd, mocked_responses: responses):
        """When neither binding exists, creates both and returns status 'Created'."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("inst", rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)

        # Publisher: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{pub_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{pub_name}"),
            json=_build_permission_binding_response(pub_name, "Publisher", ts_name),
            status=200,
        )
        # Subscriber: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{sub_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{sub_name}"),
            json=_build_permission_binding_response(sub_name, "Subscriber", ts_name),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_permission_bindings(
            eg_ctx=eg_ctx,
            instance_resource_id=instance_rid,
            topic_space_name=ts_name,
            wait_sec=0,
        )

        assert result["publisher"]["name"] == pub_name
        assert result["publisher"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        assert result["subscriber"]["name"] == sub_name
        assert result["subscriber"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        assert len(mocked_responses.calls) == 4

        # Verify publisher PUT payload
        pub_body = json.loads(mocked_responses.calls[1].request.body)
        assert pub_body["properties"]["permission"] == "Publisher"
        assert pub_body["properties"]["topicSpaceName"] == ts_name
        assert pub_body["properties"]["clientGroupName"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP

        # Verify subscriber PUT payload
        sub_body = json.loads(mocked_responses.calls[3].request.body)
        assert sub_body["properties"]["permission"] == "Subscriber"
        assert sub_body["properties"]["topicSpaceName"] == ts_name

    def test_both_bindings_exist(self, mocked_cmd, mocked_responses: responses):
        """When both bindings exist, returns status 'Exists' without any PUTs."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("inst", rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)

        # Both return 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{pub_name}"),
            json=_build_permission_binding_response(pub_name, "Publisher", ts_name),
            status=200,
        )
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{sub_name}"),
            json=_build_permission_binding_response(sub_name, "Subscriber", ts_name),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_permission_bindings(
            eg_ctx=eg_ctx,
            instance_resource_id=instance_rid,
            topic_space_name=ts_name,
            wait_sec=0,
        )

        assert result["publisher"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        assert result["subscriber"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        # Only GET calls, no PUTs
        assert len(mocked_responses.calls) == 2

    def test_mixed_exists_and_create(self, mocked_cmd, mocked_responses: responses):
        """Publisher exists, subscriber does not — creates only subscriber."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("inst", rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)

        # Publisher: GET 200 (exists)
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{pub_name}"),
            json=_build_permission_binding_response(pub_name, "Publisher", ts_name),
            status=200,
        )
        # Subscriber: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{sub_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{sub_name}"),
            json=_build_permission_binding_response(sub_name, "Subscriber", ts_name),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_permission_bindings(
            eg_ctx=eg_ctx,
            instance_resource_id=instance_rid,
            topic_space_name=ts_name,
            wait_sec=0,
        )

        assert result["publisher"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        assert result["subscriber"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        # 1 GET (pub) + 1 GET (sub 404) + 1 PUT (sub create) = 3
        assert len(mocked_responses.calls) == 3

    def test_custom_client_group(self, mocked_cmd, mocked_responses: responses):
        """Custom eg_client_group is passed through in the binding payload."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("inst", rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)
        custom_group = "myCustomGroup"

        # Both GET 404, both PUT 200
        for name, perm in [(pub_name, "Publisher"), (sub_name, "Subscriber")]:
            mocked_responses.add(
                method=responses.GET,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json={"error": {"code": "ResourceNotFound"}},
                status=404,
            )
            mocked_responses.add(
                method=responses.PUT,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json=_build_permission_binding_response(name, perm, ts_name, client_group_name=custom_group),
                status=200,
            )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_permission_bindings(
            eg_ctx=eg_ctx,
            instance_resource_id=instance_rid,
            topic_space_name=ts_name,
            eg_client_group=custom_group,
            wait_sec=0,
        )

        assert result["publisher"]["clientGroup"] == custom_group
        assert result["subscriber"]["clientGroup"] == custom_group

        # Verify custom client group in PUT payloads
        pub_body = json.loads(mocked_responses.calls[1].request.body)
        assert pub_body["properties"]["clientGroupName"] == custom_group
        sub_body = json.loads(mocked_responses.calls[3].request.body)
        assert sub_body["properties"]["clientGroupName"] == custom_group

    def test_default_client_group(self, mocked_cmd, mocked_responses: responses):
        """When eg_client_group is None, defaults to $all."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("inst", rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)

        # Both GET 404, both PUT 200
        for name, perm in [(pub_name, "Publisher"), (sub_name, "Subscriber")]:
            mocked_responses.add(
                method=responses.GET,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json={"error": {"code": "ResourceNotFound"}},
                status=404,
            )
            mocked_responses.add(
                method=responses.PUT,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json=_build_permission_binding_response(name, perm, ts_name),
                status=200,
            )

        provider = MgmtActions(cmd=mocked_cmd)
        provider._setup_eg_permission_bindings(
            eg_ctx=eg_ctx,
            instance_resource_id=instance_rid,
            topic_space_name=ts_name,
            eg_client_group=None,
            wait_sec=0,
        )

        pub_body = json.loads(mocked_responses.calls[1].request.body)
        assert pub_body["properties"]["clientGroupName"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP


# ---------------------------------------------------------------------------
# _setup_eg_dataflow_endpoint tests
# ---------------------------------------------------------------------------


class TestSetupEgDataflowEndpoint:
    """Tests for MgmtActions._setup_eg_dataflow_endpoint()."""

    def test_create_new_system_assigned(self, mocked_cmd, mocked_responses: responses):
        """When endpoint does not exist and no UAMI, creates with SystemAssigned MI."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        extended_location = _make_extended_location()

        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)

        # GET returns 404 (doesn't exist)
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # PUT creates it
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"id": f"/fake/path/dataflowEndpoints/{ep_name}", "name": ep_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_dataflow_endpoint(
            eg_ctx=eg_ctx,
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            wait_sec=0,
        )

        assert result["name"] == ep_name
        assert result["authentication"]["method"] == "SystemAssignedManagedIdentity"
        assert len(mocked_responses.calls) == 2

        # Verify the PUT payload
        put_body = json.loads(mocked_responses.calls[1].request.body)
        assert put_body["extendedLocation"] == extended_location
        props = put_body["properties"]
        assert props["endpointType"] == MQTT_ENDPOINT_TYPE
        mqtt = props["mqttSettings"]
        assert mqtt["host"] == eg_ctx.mqtt_hostname
        assert mqtt["tls"] == {"mode": "Enabled"}
        auth = mqtt["authentication"]
        assert auth["method"] == "SystemAssignedManagedIdentity"
        assert auth["systemAssignedManagedIdentitySettings"]["audience"] == MGMT_ACTIONS_EG_AUDIENCE

    def test_create_new_user_assigned(self, mocked_cmd, mocked_responses: responses):
        """When endpoint does not exist and UAMI is provided, creates with UserAssigned MI."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        extended_location = _make_extended_location()

        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)
        uami_name = generate_random_string()
        uami_rid = _build_uami_resource_id(uami_name, rg)
        uami_client_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        uami_tenant_id = "tttttttt-tttt-tttt-tttt-tttttttttttt"

        # GET dataflow endpoint returns 404
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # GET UAMI returns identity details
        mocked_responses.add(
            method=responses.GET,
            url=_build_uami_endpoint(uami_rid),
            json=_build_uami_response(uami_rid, uami_client_id, uami_tenant_id),
            status=200,
        )
        # PUT creates endpoint
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"id": f"/fake/path/dataflowEndpoints/{ep_name}", "name": ep_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_dataflow_endpoint(
            eg_ctx=eg_ctx,
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            mi_user_assigned=uami_rid,
            wait_sec=0,
        )

        assert result["name"] == ep_name
        result_auth = result["authentication"]
        assert result_auth["method"] == "UserAssignedManagedIdentity"
        assert result_auth["userAssignedManagedIdentitySettings"]["clientId"] == uami_client_id
        assert result_auth["userAssignedManagedIdentitySettings"]["tenantId"] == uami_tenant_id
        # GET endpoint (404) + GET UAMI (200) + PUT endpoint (200) = 3
        assert len(mocked_responses.calls) == 3

        # Verify the PUT payload
        put_body = json.loads(mocked_responses.calls[2].request.body)
        auth = put_body["properties"]["mqttSettings"]["authentication"]
        assert auth["method"] == "UserAssignedManagedIdentity"
        uami_settings = auth["userAssignedManagedIdentitySettings"]
        assert uami_settings["clientId"] == uami_client_id
        assert uami_settings["tenantId"] == uami_tenant_id
        assert uami_settings["scope"] == MGMT_ACTIONS_EG_AUDIENCE

    def test_existing_endpoint(self, mocked_cmd, mocked_responses: responses):
        """When endpoint already exists, returns status 'Exists' without PUT."""
        ns_name = generate_random_string()
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        eg_ctx = _make_eg_ctx(namespace_name=ns_name, resource_group_name=rg)
        extended_location = _make_extended_location()

        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)

        existing_auth = {
            "method": "SystemAssignedManagedIdentity",
            "systemAssignedManagedIdentitySettings": {"audience": MGMT_ACTIONS_EG_AUDIENCE},
        }
        # GET returns 200 (already exists)
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={
                "id": f"/fake/path/dataflowEndpoints/{ep_name}",
                "name": ep_name,
                "properties": {"mqttSettings": {"authentication": existing_auth}},
            },
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_eg_dataflow_endpoint(
            eg_ctx=eg_ctx,
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            wait_sec=0,
        )

        assert result["name"] == ep_name
        assert result["authentication"] == existing_auth
        # Only the GET call, no PUT
        assert len(mocked_responses.calls) == 1

    def test_deterministic_naming(self, mocked_cmd, mocked_responses: responses):
        """Endpoint name is deterministic based on instance resource ID."""
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("some-instance", rg)

        name_a = get_mgmt_actions_resource_name("eg", instance_rid)
        name_b = get_mgmt_actions_resource_name("eg", instance_rid)
        assert name_a == name_b
        assert name_a.startswith("mgmt-actions-eg-")
        assert len(name_a) == 24  # "mgmt-actions-eg-" (16) + hash8 (8) = 24

    def test_host_is_raw_hostname(self, mocked_cmd, mocked_responses: responses):
        """Host in the MQTT settings is the raw MQTT hostname without port."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        hostname = "my-ns.westus2-1.ts.eventgrid.azure.net"
        eg_ctx = _make_eg_ctx(
            namespace_name="my-ns",
            resource_group_name=rg,
            mqtt_hostname=hostname,
        )
        extended_location = _make_extended_location()
        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)

        # GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"id": f"/fake/path/dataflowEndpoints/{ep_name}", "name": ep_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        provider._setup_eg_dataflow_endpoint(
            eg_ctx=eg_ctx,
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            wait_sec=0,
        )

        put_body = json.loads(mocked_responses.calls[1].request.body)
        assert put_body["properties"]["mqttSettings"]["host"] == hostname
        # Verify no port appended
        assert ":" not in put_body["properties"]["mqttSettings"]["host"]

    def test_tls_enabled_no_custom_ca(self, mocked_cmd, mocked_responses: responses):
        """TLS is enabled without a custom CA configmap for EG public endpoints."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        eg_ctx = _make_eg_ctx(resource_group_name=rg)
        extended_location = _make_extended_location()
        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)

        # GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"id": f"/fake/path/dataflowEndpoints/{ep_name}", "name": ep_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        provider._setup_eg_dataflow_endpoint(
            eg_ctx=eg_ctx,
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            wait_sec=0,
        )

        put_body = json.loads(mocked_responses.calls[1].request.body)
        tls = put_body["properties"]["mqttSettings"]["tls"]
        assert tls["mode"] == "Enabled"
        assert "trustedCaCertificateConfigMapRef" not in tls

    def test_uami_not_found(self, mocked_cmd, mocked_responses: responses):
        """When UAMI resource is not found, raises InvalidArgumentValueError."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        eg_ctx = _make_eg_ctx(resource_group_name=rg)
        extended_location = _make_extended_location()
        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)
        uami_rid = _build_uami_resource_id("missing-identity", rg)

        # GET endpoint returns 404
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # GET UAMI returns 404
        mocked_responses.add(
            method=responses.GET,
            url=_build_uami_endpoint(uami_rid),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(InvalidArgumentValueError, match="not found"):
            provider._setup_eg_dataflow_endpoint(
                eg_ctx=eg_ctx,
                instance_name=instance_name,
                instance_resource_id=instance_rid,
                resource_group_name=rg,
                extended_location=extended_location,
                mi_user_assigned=uami_rid,
                wait_sec=0,
            )

        # GET endpoint (404) + GET UAMI (404) = 2, no PUT
        assert len(mocked_responses.calls) == 2


# ---------------------------------------------------------------------------
# _setup_adr_management_endpoint tests
# ---------------------------------------------------------------------------


class TestSetupAdrManagementEndpoint:
    """Tests for MgmtActions._setup_adr_management_endpoint()."""

    def _make_instance(
        self,
        instance_name: str,
        rg: str,
        adr_ns_name: str,
    ) -> dict:
        """Build a minimal instance dict with adrNamespaceRef and extendedLocation."""
        return _build_instance_response(instance_name, rg, adr_namespace_name=adr_ns_name)

    def test_create_new_identity_and_endpoint(self, mocked_cmd, mocked_responses: responses):
        """ADR namespace has no identity and no management endpoint — enables both."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        adr_ns_name = generate_random_string()
        eg_ctx = _make_eg_ctx()

        instance = self._make_instance(instance_name, rg, adr_ns_name)
        principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # GET: no identity, no management endpoints
        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(adr_ns_name, rg, identity_type="None"),
            status=200,
        )
        # PATCH: returns SystemAssigned with principalId
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
                management_endpoints={
                    instance["extendedLocation"]["name"]: {
                        "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                        "address": eg_ctx.mqtt_hostname,
                        "scopeId": instance_name,
                        "resourceId": eg_ctx.resource_id,
                    },
                },
            ),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_adr_management_endpoint(
            instance=instance,
            eg_ctx=eg_ctx,
            wait_sec=0,
        )

        assert "principalId" not in result
        assert result["name"] == adr_ns_name
        assert result["identity"]["type"] == "SystemAssigned"
        assert result["identity"]["principalId"] == principal_id
        cl_id = instance["extendedLocation"]["name"]
        assert cl_id in result["managementEndpoints"]
        assert result["managementEndpoints"][cl_id]["endpointType"] == MGMT_ACTIONS_ADR_ENDPOINT_TYPE
        assert result["managementEndpoints"][cl_id]["address"] == eg_ctx.mqtt_hostname
        assert "resourceId" not in result

        # Verify PATCH payload
        patch_body = json.loads(mocked_responses.calls[1].request.body)
        assert patch_body["identity"]["type"] == "SystemAssigned"
        mgmt_endpoints = patch_body["properties"]["management"]["endpoints"]
        cl_id = instance["extendedLocation"]["name"]
        assert cl_id in mgmt_endpoints
        assert mgmt_endpoints[cl_id]["endpointType"] == MGMT_ACTIONS_ADR_ENDPOINT_TYPE
        assert mgmt_endpoints[cl_id]["address"] == eg_ctx.mqtt_hostname
        assert mgmt_endpoints[cl_id]["scopeId"] == instance_name
        assert mgmt_endpoints[cl_id]["resourceId"] == eg_ctx.resource_id

        assert len(mocked_responses.calls) == 2

    def test_already_configured_skips_update(self, mocked_cmd, mocked_responses: responses):
        """ADR namespace already has SystemAssigned identity and matching endpoint — returns Exists."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        adr_ns_name = generate_random_string()
        eg_ctx = _make_eg_ctx()

        instance = self._make_instance(instance_name, rg, adr_ns_name)
        cl_id = instance["extendedLocation"]["name"]
        principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # GET: already has matching identity and endpoint
        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
                management_endpoints={
                    cl_id: {
                        "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                        "address": eg_ctx.mqtt_hostname,
                        "scopeId": instance_name,
                        "resourceId": eg_ctx.resource_id,
                    },
                },
            ),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_adr_management_endpoint(
            instance=instance,
            eg_ctx=eg_ctx,
        )

        assert "principalId" not in result
        assert result["name"] == adr_ns_name
        assert result["identity"]["type"] == "SystemAssigned"
        assert result["identity"]["principalId"] == principal_id
        assert cl_id in result["managementEndpoints"]
        assert result["managementEndpoints"][cl_id]["endpointType"] == MGMT_ACTIONS_ADR_ENDPOINT_TYPE

        # Only GET — no PATCH
        assert len(mocked_responses.calls) == 1

    def test_identity_exists_endpoint_missing(self, mocked_cmd, mocked_responses: responses):
        """ADR namespace has SystemAssigned identity but no management endpoint entry."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        adr_ns_name = generate_random_string()
        eg_ctx = _make_eg_ctx()

        instance = self._make_instance(instance_name, rg, adr_ns_name)
        principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # GET: has identity, no management endpoints
        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
            ),
            status=200,
        )
        # PATCH: add endpoint
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
                management_endpoints={
                    instance["extendedLocation"]["name"]: {
                        "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                        "address": eg_ctx.mqtt_hostname,
                        "scopeId": instance_name,
                        "resourceId": eg_ctx.resource_id,
                    },
                },
            ),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_adr_management_endpoint(
            instance=instance,
            eg_ctx=eg_ctx,
            wait_sec=0,
        )

        assert "principalId" not in result
        assert result["identity"]["type"] == "SystemAssigned"
        assert result["identity"]["principalId"] == principal_id
        cl_id = instance["extendedLocation"]["name"]
        assert cl_id in result["managementEndpoints"]

        # Verify PATCH does NOT include identity block (already SystemAssigned)
        patch_body = json.loads(mocked_responses.calls[1].request.body)
        assert "identity" not in patch_body

        assert len(mocked_responses.calls) == 2

    def test_preserves_existing_endpoints(self, mocked_cmd, mocked_responses: responses):
        """PATCH payload includes existing management endpoints from other custom locations."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        adr_ns_name = generate_random_string()
        eg_ctx = _make_eg_ctx()

        instance = self._make_instance(instance_name, rg, adr_ns_name)
        cl_id = instance["extendedLocation"]["name"]
        principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # Pre-existing endpoint from a different custom location
        other_cl_id = (
            "/subscriptions/other-sub/resourceGroups/other-rg"
            "/providers/Microsoft.ExtendedLocation/customLocations/other-cl"
        )
        existing_endpoints = {
            other_cl_id: {
                "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                "address": "other-host.eastus-1.ts.eventgrid.azure.net",
                "scopeId": "other-instance",
                "resourceId": (
                    "/subscriptions/other-sub/resourceGroups/other-rg"
                    "/providers/Microsoft.EventGrid/namespaces/other-ns"
                ),
            },
        }

        # GET: has identity but endpoint is for a different CL
        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
                management_endpoints=existing_endpoints,
            ),
            status=200,
        )
        # PATCH: merge endpoints — response includes both endpoints
        merged_endpoints = dict(existing_endpoints)
        merged_endpoints[cl_id] = {
            "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
            "address": eg_ctx.mqtt_hostname,
            "scopeId": instance_name,
            "resourceId": eg_ctx.resource_id,
        }
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
                management_endpoints=merged_endpoints,
            ),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_adr_management_endpoint(
            instance=instance,
            eg_ctx=eg_ctx,
            wait_sec=0,
        )

        # Both our entry and the other CL's entry should be in the result
        assert cl_id in result["managementEndpoints"]
        assert other_cl_id in result["managementEndpoints"]

        # Verify PATCH payload preserves the other CL's endpoint
        patch_body = json.loads(mocked_responses.calls[1].request.body)
        mgmt_endpoints = patch_body["properties"]["management"]["endpoints"]
        assert other_cl_id in mgmt_endpoints
        assert cl_id in mgmt_endpoints
        # Other endpoint data unchanged
        assert mgmt_endpoints[other_cl_id] == existing_endpoints[other_cl_id]

        assert len(mocked_responses.calls) == 2

    def test_endpoint_value_changed_reports_updated(self, mocked_cmd, mocked_responses: responses):
        """When the CL key exists but values differ, reports 'Updated'."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        adr_ns_name = generate_random_string()
        eg_ctx = _make_eg_ctx()

        instance = self._make_instance(instance_name, rg, adr_ns_name)
        cl_id = instance["extendedLocation"]["name"]
        principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # Existing endpoint has a stale address
        stale_endpoint = {
            cl_id: {
                "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                "address": "old-host.eventgrid.azure.net",
                "scopeId": instance_name,
                "resourceId": eg_ctx.resource_id,
            },
        }

        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
                management_endpoints=stale_endpoint,
            ),
            status=200,
        )
        # PATCH response includes the updated endpoint
        updated_endpoint = {
            cl_id: {
                "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                "address": eg_ctx.mqtt_hostname,
                "scopeId": instance_name,
                "resourceId": eg_ctx.resource_id,
            },
        }
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=principal_id,
                management_endpoints=updated_endpoint,
            ),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_adr_management_endpoint(
            instance=instance,
            eg_ctx=eg_ctx,
            wait_sec=0,
        )

        assert result["identity"]["type"] == "SystemAssigned"
        assert cl_id in result["managementEndpoints"]
        # Address should be the updated value from the PATCH response
        assert result["managementEndpoints"][cl_id]["address"] == eg_ctx.mqtt_hostname
        assert len(mocked_responses.calls) == 2

    def test_missing_adr_namespace_ref(self, mocked_cmd, mocked_responses: responses):
        """Instance without adrNamespaceRef raises ValidationError."""
        instance = _build_instance_response("test-inst", "test-rg")
        # Remove adrNamespaceRef
        instance["properties"].pop("adrNamespaceRef", None)
        eg_ctx = _make_eg_ctx()

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(ValidationError, match="adrNamespaceRef"):
            provider._setup_adr_management_endpoint(instance=instance, eg_ctx=eg_ctx)

        assert len(mocked_responses.calls) == 0

    def test_no_principal_id_in_response_raises(self, mocked_cmd, mocked_responses: responses):
        """When PATCH returns no principalId, raises ValidationError."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        adr_ns_name = generate_random_string()
        eg_ctx = _make_eg_ctx()

        instance = self._make_instance(instance_name, rg, adr_ns_name)

        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(adr_ns_name, rg, identity_type="None"),
            status=200,
        )
        # PATCH response without principalId
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(adr_ns_name, rg, identity_type="SystemAssigned"),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(ValidationError, match="principalId"):
            provider._setup_adr_management_endpoint(instance=instance, eg_ctx=eg_ctx, wait_sec=0)

        assert len(mocked_responses.calls) == 2


# ---------------------------------------------------------------------------
# _setup_dataflow_graph tests
# ---------------------------------------------------------------------------


class TestSetupDataflowGraph:
    """Tests for MgmtActions._setup_dataflow_graph()."""

    def test_create_new(self, mocked_cmd, mocked_responses: responses):
        """When graph does not exist, creates with correct nodes and connections."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        extended_location = _make_extended_location()
        profile_name = "default"
        eg_ep_name = get_mgmt_actions_resource_name("eg", instance_rid)
        graph_name = get_mgmt_actions_resource_name("req", instance_rid)

        # GET returns 404
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{profile_name}/dataflowGraphs/{graph_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # PUT creates it
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{profile_name}/dataflowGraphs/{graph_name}",
            ),
            json={"id": f"/fake/path/dataflowGraphs/{graph_name}", "name": graph_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_dataflow_graph(
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            eg_dataflow_endpoint_name=eg_ep_name,
            dataflow_profile_name=profile_name,
            wait_sec=0,
        )

        assert result["name"] == graph_name
        assert len(mocked_responses.calls) == 2

        # Verify PUT payload structure
        put_body = json.loads(mocked_responses.calls[1].request.body)
        assert put_body["extendedLocation"] == extended_location
        props = put_body["properties"]
        assert props["mode"] == "Enabled"

        # Verify 3 nodes
        nodes = props["nodes"]
        assert len(nodes) == 3

        source_node = nodes[0]
        assert source_node["name"] == "source"
        assert source_node["nodeType"] == "Source"
        assert source_node["sourceSettings"]["endpointRef"] == eg_ep_name
        assert source_node["sourceSettings"]["dataSources"] == [f"actions/requests/{instance_name}/#"]

        graph_node = nodes[1]
        assert graph_node["name"] == "graph"
        assert graph_node["nodeType"] == "Graph"
        gs = graph_node["graphSettings"]
        assert gs["registryEndpointRef"] == MGMT_ACTIONS_DEFAULT_REGISTRY_ENDPOINT
        assert gs["artifact"] == MGMT_ACTIONS_GRAPH_ARTIFACT
        # Verify configuration is a list with key-value structure
        config = gs["configuration"]
        assert isinstance(config, list)
        assert len(config) == 1
        assert config[0]["key"] == "rules"
        rules_value = json.loads(config[0]["value"])
        assert rules_value["version"] == MGMT_ACTIONS_GRAPH_RULES_VERSION
        assert len(rules_value["map"]) == 2
        assert f"^actions/requests/{instance_name}/" in rules_value["map"][0]["expression"]

        dest_node = nodes[2]
        assert dest_node["name"] == "destination"
        assert dest_node["nodeType"] == "Destination"
        assert dest_node["destinationSettings"]["endpointRef"] == MGMT_ACTIONS_DEFAULT_MQTT_ENDPOINT
        assert dest_node["destinationSettings"]["dataDestination"] == "${outputTopic}"

        # Verify 2 connections
        conns = props["nodeConnections"]
        assert len(conns) == 2
        assert conns[0]["from"]["name"] == "source"
        assert conns[0]["to"]["name"] == "graph"
        assert conns[1]["from"]["name"] == "graph"
        assert conns[1]["to"]["name"] == "destination"

    def test_already_exists(self, mocked_cmd, mocked_responses: responses):
        """When graph already exists, returns 'Exists' without PUT."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        extended_location = _make_extended_location()
        profile_name = "default"
        graph_name = get_mgmt_actions_resource_name("req", instance_rid)
        eg_ep_name = get_mgmt_actions_resource_name("eg", instance_rid)

        # GET returns 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{profile_name}/dataflowGraphs/{graph_name}",
            ),
            json={"id": f"/fake/path/dataflowGraphs/{graph_name}", "name": graph_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_dataflow_graph(
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            eg_dataflow_endpoint_name=eg_ep_name,
            dataflow_profile_name=profile_name,
            wait_sec=0,
        )

        assert result["name"] == graph_name
        assert len(mocked_responses.calls) == 1

    def test_deterministic_naming(self, mocked_cmd, mocked_responses: responses):
        """Graph name is deterministic and uses 'req' purpose."""
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("some-instance", rg)

        name_a = get_mgmt_actions_resource_name("req", instance_rid)
        name_b = get_mgmt_actions_resource_name("req", instance_rid)
        assert name_a == name_b
        assert name_a.startswith("mgmt-actions-req-")
        assert len(name_a) == 25  # "mgmt-actions-req-" (17) + hash8 (8) = 25

    def test_custom_dataflow_profile(self, mocked_cmd, mocked_responses: responses):
        """Graph is created under the specified dataflow profile, not just 'default'."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        extended_location = _make_extended_location()
        custom_profile = "my-custom-profile"
        graph_name = get_mgmt_actions_resource_name("req", instance_rid)
        eg_ep_name = get_mgmt_actions_resource_name("eg", instance_rid)

        # GET returns 404
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflowGraphs/{graph_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # PUT creates it
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflowGraphs/{graph_name}",
            ),
            json={"id": f"/fake/path/dataflowGraphs/{graph_name}", "name": graph_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_dataflow_graph(
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            eg_dataflow_endpoint_name=eg_ep_name,
            dataflow_profile_name=custom_profile,
            wait_sec=0,
        )

        assert result["name"] == graph_name
        assert len(mocked_responses.calls) == 2


# ---------------------------------------------------------------------------
# _build_graph_rules_config tests
# ---------------------------------------------------------------------------


class TestBuildGraphRulesConfig:
    """Tests for the _build_graph_rules_config module-level helper."""

    def test_produces_valid_config_list(self):
        """Output is a key-value list with a JSON string rules value."""
        result = _build_graph_rules_config(topic_prefix_regex="^actions/requests/myinst/")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["key"] == "rules"
        rules_value = json.loads(result[0]["value"])
        assert rules_value["version"] == MGMT_ACTIONS_GRAPH_RULES_VERSION
        assert rules_value["datasets"] == []
        assert len(rules_value["map"]) == 2

    def test_topic_prefix_regex_in_expression(self):
        """The topic prefix regex is embedded in the regex_replace expression."""
        regex = "^actions/requests/[^/]+/"
        result = _build_graph_rules_config(topic_prefix_regex=regex)
        rules_value = json.loads(result[0]["value"])
        strip_entry = rules_value["map"][0]
        assert strip_entry["description"] == "Strip the topic prefix"
        assert strip_entry["inputs"] == ["$metadata.topic"]
        assert strip_entry["output"] == "$metadata.topic"
        assert regex in strip_entry["expression"]

    def test_copy_payload_entry(self):
        """The second map entry copies the full payload through."""
        result = _build_graph_rules_config(topic_prefix_regex="^test/")
        rules_value = json.loads(result[0]["value"])
        copy_entry = rules_value["map"][1]
        assert copy_entry["description"] == "Copy the payload"
        assert copy_entry["inputs"] == ["*"]
        assert copy_entry["output"] == "*"


# ---------------------------------------------------------------------------
# _setup_response_dataflow tests
# ---------------------------------------------------------------------------


class TestSetupResponseDataflow:
    """Tests for MgmtActions._setup_response_dataflow — response (edge→cloud) dataflow resource."""

    def test_create_new(self, mocked_cmd, mocked_responses: responses):
        """Creates a new response dataflow with correct operations payload."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        extended_location = _make_extended_location()
        profile_name = "default"
        eg_ep_name = get_mgmt_actions_resource_name("eg", instance_rid)
        dataflow_name = get_mgmt_actions_resource_name("resp", instance_rid)

        # GET returns 404
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{profile_name}/dataflows/{dataflow_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # PUT returns 200
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{profile_name}/dataflows/{dataflow_name}",
            ),
            json={"id": f"/fake/path/dataflows/{dataflow_name}", "name": dataflow_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_response_dataflow(
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            eg_dataflow_endpoint_name=eg_ep_name,
            dataflow_profile_name=profile_name,
            wait_sec=0,
        )

        assert result["name"] == dataflow_name

        # Verify PUT body
        put_body = json.loads(mocked_responses.calls[1].request.body)
        assert put_body["extendedLocation"] == extended_location
        props = put_body["properties"]
        assert props["mode"] == "Enabled"

        ops = props["operations"]
        assert len(ops) == 2

        # Source operation — local MQTT broker
        source_op = ops[0]
        assert source_op["operationType"] == "Source"
        assert source_op["sourceSettings"]["endpointRef"] == MGMT_ACTIONS_DEFAULT_MQTT_ENDPOINT
        expected_topic = MGMT_ACTIONS_RESPONSE_TOPIC_TEMPLATE.format(scope_id=instance_name)
        assert source_op["sourceSettings"]["dataSources"] == [expected_topic]

        # Destination operation — EG endpoint
        dest_op = ops[1]
        assert dest_op["operationType"] == "Destination"
        assert dest_op["destinationSettings"]["endpointRef"] == eg_ep_name
        assert dest_op["destinationSettings"]["dataDestination"] == "${inputTopic}"

        assert len(mocked_responses.calls) == 2

    def test_already_exists(self, mocked_cmd, mocked_responses: responses):
        """Returns Exists status when the response dataflow already exists."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        extended_location = _make_extended_location()
        profile_name = "default"
        dataflow_name = get_mgmt_actions_resource_name("resp", instance_rid)

        # GET returns 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{profile_name}/dataflows/{dataflow_name}",
            ),
            json={"id": f"/fake/path/dataflows/{dataflow_name}", "name": dataflow_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_response_dataflow(
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            eg_dataflow_endpoint_name="some-ep",
            dataflow_profile_name=profile_name,
            wait_sec=0,
        )

        assert result["name"] == dataflow_name
        assert len(mocked_responses.calls) == 1

    def test_deterministic_naming(self, mocked_cmd, mocked_responses: responses):
        """Dataflow name is deterministic and uses 'resp' purpose."""
        rg = generate_random_string()
        instance_rid = _build_eg_resource_id("some-instance", rg)

        name_a = get_mgmt_actions_resource_name("resp", instance_rid)
        name_b = get_mgmt_actions_resource_name("resp", instance_rid)
        assert name_a == name_b
        assert name_a.startswith("mgmt-actions-resp-")
        assert len(name_a) == 26  # "mgmt-actions-resp-" (18) + hash8 (8) = 26

    def test_custom_dataflow_profile(self, mocked_cmd, mocked_responses: responses):
        """Response dataflow is created under the specified dataflow profile."""
        rg = generate_random_string()
        instance_name = generate_random_string()
        instance_rid = _build_eg_resource_id(instance_name, rg)
        extended_location = _make_extended_location()
        custom_profile = "my-custom-profile"
        dataflow_name = get_mgmt_actions_resource_name("resp", instance_rid)
        eg_ep_name = get_mgmt_actions_resource_name("eg", instance_rid)

        # GET returns 404
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflows/{dataflow_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        # PUT returns 200
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflows/{dataflow_name}",
            ),
            json={"id": f"/fake/path/dataflows/{dataflow_name}", "name": dataflow_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider._setup_response_dataflow(
            instance_name=instance_name,
            instance_resource_id=instance_rid,
            resource_group_name=rg,
            extended_location=extended_location,
            eg_dataflow_endpoint_name=eg_ep_name,
            dataflow_profile_name=custom_profile,
            wait_sec=0,
        )

        assert result["name"] == dataflow_name

        # Verify the PUT went to the custom profile URL
        put_url = mocked_responses.calls[1].request.url
        assert f"/dataflowProfiles/{custom_profile}/" in put_url

        assert len(mocked_responses.calls) == 2


# ---------------------------------------------------------------------------
# enable() orchestration tests
# ---------------------------------------------------------------------------


class TestEnable:
    """Tests for MgmtActions.enable() — orchestration wiring and return structure.

    Individual sub-method logic (payloads, error paths, naming) is tested in
    the dedicated Test* classes above. These tests focus on how enable() ties
    the stages together and the shape of the return object.
    """

    def test_happy_path_return_structure(self, mocked_cmd, mocked_responses: responses):
        """All resources created fresh — validates return object shape and key data flow."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        ns_name = generate_random_string()
        hostname = f"{ns_name}.eastus-1.ts.eventgrid.azure.net"

        instance_response = _build_instance_response(instance_name, rg)
        instance_rid = instance_response["id"]
        cl_id = instance_response["extendedLocation"]["name"]
        eg_rid = _build_eg_resource_id(ns_name, rg)
        adr_ns_name = f"{instance_name}-adr-ns"
        adr_principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)
        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)
        graph_name = get_mgmt_actions_resource_name("req", instance_rid)
        resp_name = get_mgmt_actions_resource_name("resp", instance_rid)

        # 1. GET instance
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg),
            json=instance_response,
            status=200,
        )
        # 2. GET EG namespace
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg),
            json=_build_namespace_response(ns_name, rg, mqtt_hostname=hostname),
            status=200,
        )
        # 3-4. Topic space: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json=_build_topic_space_response(ts_name, _get_expected_topic_templates(instance_name)),
            status=200,
        )
        # 5-8. Permission bindings (pub + sub): each GET 404, PUT 200
        for name, perm in [(pub_name, "Publisher"), (sub_name, "Subscriber")]:
            mocked_responses.add(
                method=responses.GET,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json={"error": {"code": "ResourceNotFound"}},
                status=404,
            )
            mocked_responses.add(
                method=responses.PUT,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json=_build_permission_binding_response(name, perm, ts_name),
                status=200,
            )
        # 9-10. Dataflow endpoint: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"id": f"/fake/path/dataflowEndpoints/{ep_name}", "name": ep_name},
            status=200,
        )
        # 11-12. ADR namespace: GET, PATCH 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(adr_ns_name, rg, identity_type="None"),
            status=200,
        )
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=adr_principal_id,
                management_endpoints={
                    cl_id: {
                        "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                        "address": hostname,
                        "scopeId": instance_name,
                        "resourceId": eg_rid,
                    },
                },
            ),
            status=200,
        )
        # 13-14. Dataflow graph: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflowGraphs/{graph_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflowGraphs/{graph_name}",
            ),
            json={"id": f"/fake/path/dataflowGraphs/{graph_name}", "name": graph_name},
            status=200,
        )
        # 13-14. Response dataflow: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflows/{resp_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflows/{resp_name}",
            ),
            json={"id": f"/fake/path/dataflows/{resp_name}", "name": resp_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider.enable(
            name=instance_name,
            resource_group_name=rg,
            eg_resource_id=eg_rid,
            wait_sec=0,
        )

        # -- Assert top-level keys --
        assert set(result.keys()) == {"instance", "eventGrid", "deviceRegistryNamespace"}

        # -- Assert instance section --
        inst = result["instance"]
        assert inst["name"] == instance_name
        assert inst["resourceGroup"] == rg
        assert "resourceId" not in inst
        assert inst["version"] == MIN_INSTANCE_VERSION_MGMT_ACTIONS
        assert inst["dataflowProfile"] == MGMT_ACTIONS_DEFAULT_DATAFLOW_PROFILE
        # dataflowEndpoint is an instance child resource, not under eventGrid
        assert "dataflowEndpoint" in inst
        assert inst["dataflowEndpoint"]["name"] == ep_name
        assert inst["requestDataflowGraph"]["name"] == graph_name
        assert inst["responseDataflow"]["name"] == resp_name

        # -- Assert eventGrid section --
        eg = result["eventGrid"]
        assert eg["namespace"]["name"] == ns_name
        assert "resourceId" not in eg["namespace"]
        assert eg["namespace"]["resourceGroup"] == rg
        assert eg["namespace"]["subscriptionId"] == ZEROED_SUBSCRIPTION
        assert eg["namespace"]["mqttHostname"] == hostname
        assert "dataflowEndpoint" not in eg  # must not be here

        assert eg["topicSpace"]["name"] == ts_name
        assert eg["topicSpace"]["scopeId"] == instance_name

        assert eg["permissionBindings"]["publisher"]["name"] == pub_name
        assert eg["permissionBindings"]["publisher"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        assert eg["permissionBindings"]["subscriber"]["name"] == sub_name
        assert eg["permissionBindings"]["subscriber"]["clientGroup"] == MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP

        # -- Assert deviceRegistryNamespace section --
        adr = result["deviceRegistryNamespace"]
        assert "principalId" not in adr
        assert adr["identity"]["type"] == "SystemAssigned"
        assert adr["identity"]["principalId"] == adr_principal_id

        # -- Assert total HTTP call count: 16 --
        # GET instance + GET EG namespace + (GET+PUT topic space) +
        # (GET+PUT pub binding) + (GET+PUT sub binding) + (GET+PUT endpoint) +
        # (GET+PATCH ADR namespace) + (GET+PUT dataflow graph) + (GET+PUT response dataflow)
        assert len(mocked_responses.calls) == 16

    def test_version_below_minimum(self, mocked_cmd, mocked_responses: responses):
        """enable() raises ValidationError when instance version is below the minimum."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        ns_name = generate_random_string()
        eg_rid = _build_eg_resource_id(ns_name, rg)

        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg),
            json=_build_instance_response(instance_name, rg, version="1.0.0"),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(ValidationError, match="does not meet the minimum"):
            provider.enable(
                name=instance_name,
                resource_group_name=rg,
                eg_resource_id=eg_rid,
                wait_sec=0,
            )

        assert len(mocked_responses.calls) == 1

    def test_empty_version_string(self, mocked_cmd, mocked_responses: responses):
        """enable() raises ValidationError when instance version is an empty string."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        ns_name = generate_random_string()
        eg_rid = _build_eg_resource_id(ns_name, rg)

        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg),
            json=_build_instance_response(instance_name, rg, version=""),
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        with pytest.raises(ValidationError, match="does not meet the minimum"):
            provider.enable(
                name=instance_name,
                resource_group_name=rg,
                eg_resource_id=eg_rid,
                wait_sec=0,
            )

        assert len(mocked_responses.calls) == 1

    def test_custom_dataflow_profile(self, mocked_cmd, mocked_responses: responses):
        """enable() uses a custom dataflow profile name when provided."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        ns_name = generate_random_string()
        hostname = f"{ns_name}.eastus-1.ts.eventgrid.azure.net"
        custom_profile = "my-custom-profile"

        instance_response = _build_instance_response(instance_name, rg)
        instance_rid = instance_response["id"]
        cl_id = instance_response["extendedLocation"]["name"]
        eg_rid = _build_eg_resource_id(ns_name, rg)
        adr_ns_name = f"{instance_name}-adr-ns"
        adr_principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)
        graph_name = get_mgmt_actions_resource_name("req", instance_rid)
        resp_name = get_mgmt_actions_resource_name("resp", instance_rid)
        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)

        # 1. GET instance
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg),
            json=instance_response,
            status=200,
        )
        # 2. GET EG namespace
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg),
            json=_build_namespace_response(ns_name, rg, mqtt_hostname=hostname),
            status=200,
        )
        # 3-4. Topic space: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json=_build_topic_space_response(ts_name, _get_expected_topic_templates(instance_name)),
            status=200,
        )
        # 5-8. Permission bindings (pub + sub): each GET 404, PUT 200
        for name, perm in [(pub_name, "Publisher"), (sub_name, "Subscriber")]:
            mocked_responses.add(
                method=responses.GET,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json={"error": {"code": "ResourceNotFound"}},
                status=404,
            )
            mocked_responses.add(
                method=responses.PUT,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json=_build_permission_binding_response(name, perm, ts_name),
                status=200,
            )
        # 9-10. Dataflow endpoint: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"id": f"/fake/path/dataflowEndpoints/{ep_name}", "name": ep_name},
            status=200,
        )
        # 11-12. ADR namespace: GET, PATCH 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(adr_ns_name, rg, identity_type="None"),
            status=200,
        )
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=adr_principal_id,
                management_endpoints={
                    cl_id: {
                        "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                        "address": hostname,
                        "scopeId": instance_name,
                        "resourceId": eg_rid,
                    },
                },
            ),
            status=200,
        )
        # 13-14. Dataflow graph: GET 404, PUT 200 — uses custom profile
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflowGraphs/{graph_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflowGraphs/{graph_name}",
            ),
            json={"id": f"/fake/path/dataflowGraphs/{graph_name}", "name": graph_name},
            status=200,
        )
        # 13-14. Response dataflow: GET 404, PUT 200 — uses custom profile
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflows/{resp_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/{custom_profile}/dataflows/{resp_name}",
            ),
            json={"id": f"/fake/path/dataflows/{resp_name}", "name": resp_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider.enable(
            name=instance_name,
            resource_group_name=rg,
            eg_resource_id=eg_rid,
            dataflow_profile=custom_profile,
            wait_sec=0,
        )

        assert result["instance"]["requestDataflowGraph"]["name"] == graph_name
        assert result["instance"]["responseDataflow"]["name"] == resp_name
        assert result["instance"]["dataflowProfile"] == custom_profile

        # Verify the response dataflow PUT went to the custom profile URL
        resp_put_url = mocked_responses.calls[-1].request.url
        assert f"/dataflowProfiles/{custom_profile}/" in resp_put_url

        assert len(mocked_responses.calls) == 16

    def test_user_assigned_mi(self, mocked_cmd, mocked_responses: responses):
        """enable() configures UserAssignedManagedIdentity auth when mi_user_assigned is provided."""
        instance_name = generate_random_string()
        rg = generate_random_string()
        ns_name = generate_random_string()
        hostname = f"{ns_name}.eastus-1.ts.eventgrid.azure.net"
        mi_name = generate_random_string()
        mi_client_id = "11111111-1111-1111-1111-111111111111"
        mi_tenant_id = "22222222-2222-2222-2222-222222222222"

        instance_response = _build_instance_response(instance_name, rg)
        instance_rid = instance_response["id"]
        cl_id = instance_response["extendedLocation"]["name"]
        eg_rid = _build_eg_resource_id(ns_name, rg)
        mi_rid = _build_uami_resource_id(mi_name, rg)
        adr_ns_name = f"{instance_name}-adr-ns"
        adr_principal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        ep_name = get_mgmt_actions_resource_name("eg", instance_rid)
        graph_name = get_mgmt_actions_resource_name("req", instance_rid)
        resp_name = get_mgmt_actions_resource_name("resp", instance_rid)
        ts_name = get_mgmt_actions_resource_name("ops", instance_rid)
        pub_name = get_mgmt_actions_resource_name("pub", instance_rid)
        sub_name = get_mgmt_actions_resource_name("sub", instance_rid)

        # 1. GET instance
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg),
            json=instance_response,
            status=200,
        )
        # 2. GET EG namespace
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg),
            json=_build_namespace_response(ns_name, rg, mqtt_hostname=hostname),
            status=200,
        )
        # 3-4. Topic space: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/topicSpaces/{ts_name}"),
            json=_build_topic_space_response(ts_name, _get_expected_topic_templates(instance_name)),
            status=200,
        )
        # 5-8. Permission bindings (pub + sub): each GET 404, PUT 200
        for name, perm in [(pub_name, "Publisher"), (sub_name, "Subscriber")]:
            mocked_responses.add(
                method=responses.GET,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json={"error": {"code": "ResourceNotFound"}},
                status=404,
            )
            mocked_responses.add(
                method=responses.PUT,
                url=_build_eg_endpoint(ns_name, rg, sub_resource=f"/permissionBindings/{name}"),
                json=_build_permission_binding_response(name, perm, ts_name),
                status=200,
            )
        # 9. GET user-assigned managed identity
        mocked_responses.add(
            method=responses.GET,
            url=_build_uami_endpoint(mi_rid),
            json=_build_uami_response(mi_rid, mi_client_id, mi_tenant_id),
            status=200,
        )
        # 10-11. Dataflow endpoint: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(instance_name, rg, sub_resource=f"/dataflowEndpoints/{ep_name}"),
            json={"id": f"/fake/path/dataflowEndpoints/{ep_name}", "name": ep_name},
            status=200,
        )
        # 12-13. ADR namespace: GET, PATCH 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(adr_ns_name, rg, identity_type="None"),
            status=200,
        )
        mocked_responses.add(
            method=responses.PATCH,
            url=_build_adr_endpoint(adr_ns_name, rg),
            json=_build_adr_namespace_response(
                adr_ns_name,
                rg,
                identity_type="SystemAssigned",
                principal_id=adr_principal_id,
                management_endpoints={
                    cl_id: {
                        "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
                        "address": hostname,
                        "scopeId": instance_name,
                        "resourceId": eg_rid,
                    },
                },
            ),
            status=200,
        )
        # 14-15. Dataflow graph: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflowGraphs/{graph_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflowGraphs/{graph_name}",
            ),
            json={"id": f"/fake/path/dataflowGraphs/{graph_name}", "name": graph_name},
            status=200,
        )
        # 14-15. Response dataflow: GET 404, PUT 200
        mocked_responses.add(
            method=responses.GET,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflows/{resp_name}",
            ),
            json={"error": {"code": "ResourceNotFound"}},
            status=404,
        )
        mocked_responses.add(
            method=responses.PUT,
            url=_build_iotops_endpoint(
                instance_name,
                rg,
                sub_resource=f"/dataflowProfiles/default/dataflows/{resp_name}",
            ),
            json={"id": f"/fake/path/dataflows/{resp_name}", "name": resp_name},
            status=200,
        )

        provider = MgmtActions(cmd=mocked_cmd)
        result = provider.enable(
            name=instance_name,
            resource_group_name=rg,
            eg_resource_id=eg_rid,
            mi_user_assigned=mi_rid,
            wait_sec=0,
        )

        assert result["instance"]["dataflowEndpoint"]["name"] == ep_name

        # Verify the endpoint PUT body contains UserAssignedManagedIdentity auth
        endpoint_put_call = mocked_responses.calls[10]
        endpoint_body = json.loads(endpoint_put_call.request.body)
        auth = endpoint_body["properties"]["mqttSettings"]["authentication"]
        assert auth["method"] == "UserAssignedManagedIdentity"
        uami_settings = auth["userAssignedManagedIdentitySettings"]
        assert uami_settings["clientId"] == mi_client_id
        assert uami_settings["tenantId"] == mi_tenant_id
        assert uami_settings["scope"] == MGMT_ACTIONS_EG_AUDIENCE

        assert len(mocked_responses.calls) == 17
