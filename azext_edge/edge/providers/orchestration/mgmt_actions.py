# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import json
from typing import TYPE_CHECKING, Dict, List, NamedTuple, Optional

from azure.cli.core.azclierror import InvalidArgumentValueError, ValidationError
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from knack.log import get_logger

from ...util.az_client import (
    get_eventgrid_mgmt_client,
    get_iotops_mgmt_client,
    get_registry_mgmt_client,
    wait_for_terminal_state,
)
from ...util.id_tools import parse_resource_id as parse_resource_id_dict
from ...util.queryable import Queryable
from .common import (
    CUSTOM_LOCATIONS_API_VERSION,
    EG_TOPICSPACES_PUBLISHER_ROLE_ID,
    EG_TOPICSPACES_SUBSCRIBER_ROLE_ID,
    EXTENSION_TYPE_OPS,
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
    MGMT_ACTIONS_RESOURCE_PREFIX,
    MGMT_ACTIONS_RESPONSE_TOPIC_TEMPLATE,
    MIN_INSTANCE_VERSION_MGMT_ACTIONS,
    MQTT_ENDPOINT_TYPE,
)
from .connected_cluster import ConnectedCluster
from .permissions import ROLE_DEF_FORMAT_STR, PermissionManager, PrincipalType

if TYPE_CHECKING:
    from ...vendor.clients.deviceregistrymgmt import MicrosoftDeviceRegistryManagementService
    from ...vendor.clients.eventgridmgmt import EventGridManagementClient

logger = get_logger(__name__)


def get_mgmt_actions_resource_name(purpose: str, instance_resource_id: str) -> str:
    """Build a deterministic resource name for mgmt-actions resources.

    Format: mgmt-actions-{purpose}-{hash8}
    Where hash8 = first 8 chars of sha256(instance_resource_id).
    """
    from ...util.common import url_safe_hash_phrase

    hash8 = url_safe_hash_phrase(instance_resource_id)[:8]
    return f"{MGMT_ACTIONS_RESOURCE_PREFIX}-{purpose}-{hash8}"


def _build_graph_rules_config(topic_prefix_regex: str) -> List[Dict]:
    """Build the configuration array for the graph-dataflow-map rules engine.

    Returns a key-value configuration list where the 'rules' key contains a JSON
    string describing how to strip the topic prefix and copy the payload through.
    The topic_prefix_regex anchors the regex_replace to the instance-scoped request
    topic namespace.
    """
    rules_value = {
        "version": MGMT_ACTIONS_GRAPH_RULES_VERSION,
        "datasets": [],
        "map": [
            {
                "description": "Strip the topic prefix",
                "inputs": ["$metadata.topic"],
                "output": "$metadata.topic",
                "expression": f'str::regex_replace($1, "{topic_prefix_regex}", "")',
            },
            {
                "description": "Copy the payload",
                "inputs": ["*"],
                "output": "*",
            },
        ],
    }
    return [
        {
            "key": "rules",
            "value": json.dumps(rules_value),
        },
    ]


class EgNamespaceContext(NamedTuple):
    """Validated Event Grid namespace context, produced by _validate_eg_namespace().

    Set once during validation, then shared read-only across all subsequent setup
    methods. Immutable NamedTuple ensures thread safety if concurrency is added later.
    """

    resource_id: str
    subscription_id: str
    resource_group_name: str
    namespace_name: str
    mqtt_hostname: str


class MgmtActions(Queryable):
    """Provider for management actions (outer loop) enable/disable operations."""

    def __init__(self, cmd, subscription_id: Optional[str] = None):
        super().__init__(cmd=cmd, subscription_id=subscription_id)
        self.iotops_mgmt_client = get_iotops_mgmt_client(
            subscription_id=self.default_subscription_id,
        )
        self.registry_mgmt_client: "MicrosoftDeviceRegistryManagementService" = get_registry_mgmt_client(
            subscription_id=self.default_subscription_id,
        )
        # May be replaced with a cross-subscription client by _validate_eg_namespace
        self.eventgrid_mgmt_client: "EventGridManagementClient" = get_eventgrid_mgmt_client(
            subscription_id=self.default_subscription_id,
        )
        self.permission_manager = PermissionManager(self.default_subscription_id)

    def enable(
        self,
        name: str,
        resource_group_name: str,
        eg_resource_id: str,
        mi_user_assigned: Optional[str] = None,
        eg_client_group: Optional[str] = None,
        adr_role_ids: Optional[List[str]] = None,
        ops_role_ids: Optional[List[str]] = None,
        skip_role_assignments: Optional[bool] = None,
        dataflow_profile: Optional[str] = None,
        **kwargs,
    ) -> Dict:
        """Enable management actions for an IoT Operations instance.

        Bootstraps the outer loop infrastructure across Event Grid, ADR, and AIO domains.
        """
        from ...util.machinery import scoped_semver_import

        semver = scoped_semver_import()

        # Resolve instance
        instance = self.iotops_mgmt_client.instance.get(
            instance_name=name,
            resource_group_name=resource_group_name,
        )
        instance_resource_id: str = instance["id"]

        # Validate instance version
        instance_version = instance.get("properties", {}).get("version", "")
        if not instance_version or (semver.parse(instance_version) < semver.parse(MIN_INSTANCE_VERSION_MGMT_ACTIONS)):
            raise ValidationError(
                f"Instance '{name}' version '{instance_version}' does not meet the minimum "
                f"required version '{MIN_INSTANCE_VERSION_MGMT_ACTIONS}' for management actions."
            )

        # Validate EG namespace (format, existence, topic spaces, MQTT hostname)
        eg_ctx = self._validate_eg_namespace(eg_resource_id)

        # Extract extendedLocation from instance (needed for AIO child resources)
        extended_location: Dict = instance["extendedLocation"]

        # Resolve UAMI once (used by EG dataflow endpoint + identity resolution)
        mi_resource = self._resolve_user_assigned_mi(mi_user_assigned) if mi_user_assigned else None

        # Event Grid infrastructure setup
        topic_space_result = self._setup_eg_topic_space(
            eg_ctx=eg_ctx,
            instance_name=name,
            instance_resource_id=instance_resource_id,
            **kwargs,
        )

        permission_bindings_result = self._setup_eg_permission_bindings(
            eg_ctx=eg_ctx,
            instance_resource_id=instance_resource_id,
            topic_space_name=topic_space_result["name"],
            eg_client_group=eg_client_group,
            **kwargs,
        )

        # EG dataflow endpoint
        dataflow_endpoint_result = self._setup_eg_dataflow_endpoint(
            eg_ctx=eg_ctx,
            instance_name=name,
            instance_resource_id=instance_resource_id,
            resource_group_name=resource_group_name,
            extended_location=extended_location,
            mi_resource=mi_resource,
            **kwargs,
        )

        # ADR namespace — enable system MI + configure management endpoint
        adr_result = self._setup_adr_management_endpoint(
            instance=instance,
            eg_ctx=eg_ctx,
            **kwargs,
        )

        # Dataflow graph (uses default registry endpoint provisioned with instance)
        resolved_profile = dataflow_profile or MGMT_ACTIONS_DEFAULT_DATAFLOW_PROFILE

        dataflow_graph_result = self._setup_dataflow_graph(
            instance_name=name,
            instance_resource_id=instance_resource_id,
            resource_group_name=resource_group_name,
            extended_location=extended_location,
            eg_dataflow_endpoint_name=dataflow_endpoint_result["name"],
            dataflow_profile_name=resolved_profile,
            **kwargs,
        )

        # Response dataflow (edge→cloud: local MQTT → EG)
        response_dataflow_result = self._setup_response_dataflow(
            instance_name=name,
            instance_resource_id=instance_resource_id,
            resource_group_name=resource_group_name,
            extended_location=extended_location,
            eg_dataflow_endpoint_name=dataflow_endpoint_result["name"],
            dataflow_profile_name=resolved_profile,
            **kwargs,
        )

        # Role assignments — ADR namespace MI + dataflow auth identity → EG namespace
        role_assignments_result = None
        if not skip_role_assignments:
            dataflow_auth_principal_id = self._resolve_dataflow_auth_identity(
                instance=instance,
                mi_resource=mi_resource,
            )
            role_assignments_result = self._setup_role_assignments(
                eg_ctx=eg_ctx,
                adr_principal_id=adr_result["identity"]["principalId"],
                dataflow_auth_principal_id=dataflow_auth_principal_id,
                adr_role_ids=adr_role_ids,
                ops_role_ids=ops_role_ids,
            )

        result: Dict = {
            "instance": {
                "name": name,
                "resourceGroup": resource_group_name,
                "version": instance_version,
                "dataflowProfile": resolved_profile,
                "dataflowEndpoint": dataflow_endpoint_result,
                "requestDataflowGraph": dataflow_graph_result,
                "responseDataflow": response_dataflow_result,
            },
            "eventGrid": {
                "namespace": {
                    "name": eg_ctx.namespace_name,
                    "resourceGroup": eg_ctx.resource_group_name,
                    "subscriptionId": eg_ctx.subscription_id,
                    "mqttHostname": eg_ctx.mqtt_hostname,
                },
                "topicSpace": topic_space_result,
                "permissionBindings": permission_bindings_result,
            },
            "deviceRegistryNamespace": adr_result,
        }

        if role_assignments_result is not None:
            result["roleAssignments"] = role_assignments_result

        return result

    def disable(
        self,
        name: str,
        resource_group_name: str,
        confirm_yes: Optional[bool] = None,
        **kwargs,
    ) -> None:
        """Disable management actions for an IoT Operations instance.

        Tears down outer loop resources: dataflow graph, response dataflow, EG dataflow endpoint,
        EG topic space/permission bindings, and ADR namespace management endpoint entry.
        """
        raise NotImplementedError("mgmt-actions disable is not yet implemented")

    def _validate_eg_namespace(self, eg_resource_id: str) -> EgNamespaceContext:
        """Parse, fetch, and validate an Event Grid namespace for mgmt-actions use.

        Validates that the resource ID is a well-formed Microsoft.EventGrid/namespaces ID,
        the namespace exists, and MQTT broker (topic spaces) is enabled. When the namespace
        resides in a different subscription, a cross-subscription EG client is created and
        stored as self.eventgrid_mgmt_client for use by subsequent EG setup methods.
        """
        parsed = parse_resource_id_dict(eg_resource_id)

        # Validate resource type
        eg_namespace = parsed.get("namespace", "")
        eg_type = parsed.get("type", "")
        if eg_namespace.lower() != "microsoft.eventgrid" or eg_type.lower() != "namespaces":
            raise InvalidArgumentValueError(
                f"--eg-resource-id must reference a Microsoft.EventGrid/namespaces resource.\n"
                f"Got: {eg_namespace}/{eg_type}\n"
                f"Expected format: /subscriptions/{{subscriptionId}}/resourceGroups/{{resourceGroup}}"
                f"/providers/Microsoft.EventGrid/namespaces/{{namespaceName}}"
            )

        eg_subscription_id = parsed.get("subscription", "")
        eg_resource_group = parsed.get("resource_group", "")
        eg_name = parsed.get("name", "")

        if not all([eg_subscription_id, eg_resource_group, eg_name]):
            raise InvalidArgumentValueError(
                f"Malformed resource Id '{eg_resource_id}'. Could not extract subscription, "
                f"resource group, or namespace name."
            )

        # Handle cross-subscription: create a new EG client if needed
        if eg_subscription_id.lower() != self.default_subscription_id.lower():
            logger.info(
                "Event Grid namespace is in subscription '%s' (instance subscription: '%s'). "
                "Creating cross-subscription client.",
                eg_subscription_id,
                self.default_subscription_id,
            )
            self.eventgrid_mgmt_client = get_eventgrid_mgmt_client(subscription_id=eg_subscription_id)

        # Fetch the namespace
        try:
            namespace_resource = self.eventgrid_mgmt_client.namespaces.get(
                resource_group_name=eg_resource_group,
                namespace_name=eg_name,
            )
        except ResourceNotFoundError:
            raise InvalidArgumentValueError(
                f"Event Grid namespace '{eg_name}' not found in resource group '{eg_resource_group}' "
                f"(subscription: {eg_subscription_id}).\n"
                f"Verify the --eg-resource-id value and ensure the namespace exists."
            )

        # Validate topic spaces enabled
        topic_spaces_config = namespace_resource.get("properties", {}).get("topicSpacesConfiguration", {})
        topic_spaces_state = topic_spaces_config.get("state", "")
        if topic_spaces_state != "Enabled":
            state_detail = (
                f"Current state: '{topic_spaces_state}'."
                if topic_spaces_state
                else "MQTT broker has not been configured."
            )
            raise ValidationError(
                f"Event Grid namespace '{eg_name}' does not have MQTT broker (topic spaces) enabled.\n"
                f"{state_detail} "
                f"Enable topic spaces on the namespace before running mgmt-actions enable."
            )

        mqtt_hostname = topic_spaces_config.get("hostname", "")
        if not mqtt_hostname:
            raise ValidationError(
                f"Event Grid namespace '{eg_name}' has topic spaces enabled but no MQTT hostname. "
                f"This may indicate the namespace is still provisioning."
            )

        return EgNamespaceContext(
            resource_id=eg_resource_id,
            subscription_id=eg_subscription_id,
            resource_group_name=eg_resource_group,
            namespace_name=eg_name,
            mqtt_hostname=mqtt_hostname,
        )

    def _setup_eg_topic_space(
        self,
        eg_ctx: EgNamespaceContext,
        instance_name: str,
        instance_resource_id: str,
        **kwargs,
    ) -> Dict:
        """Create or confirm the mgmt-actions topic space on the EG namespace.

        Uses GET-then-PUT to report accurate status. The topic space includes both
        request and response topic templates scoped to the instance name.
        """
        topic_space_name = get_mgmt_actions_resource_name("ops", instance_resource_id)
        request_template = MGMT_ACTIONS_REQUEST_TOPIC_TEMPLATE.format(scope_id=instance_name)
        response_template = MGMT_ACTIONS_RESPONSE_TOPIC_TEMPLATE.format(scope_id=instance_name)
        topic_templates = [request_template, response_template]

        # Check if topic space already exists
        try:
            self.eventgrid_mgmt_client.topic_spaces.get(
                resource_group_name=eg_ctx.resource_group_name,
                namespace_name=eg_ctx.namespace_name,
                topic_space_name=topic_space_name,
            )
            logger.info("Topic space '%s' already exists on namespace '%s'.", topic_space_name, eg_ctx.namespace_name)
            return {
                "name": topic_space_name,
                "topicTemplates": topic_templates,
                "scopeId": instance_name,
            }
        except ResourceNotFoundError:
            pass

        # Create the topic space
        topic_space_payload = {
            "properties": {
                "description": (f"Management actions topic space for IoT Operations instance '{instance_name}'."),
                "topicTemplates": topic_templates,
            }
        }

        poller = self.eventgrid_mgmt_client.topic_spaces.begin_create_or_update(
            resource_group_name=eg_ctx.resource_group_name,
            namespace_name=eg_ctx.namespace_name,
            topic_space_name=topic_space_name,
            topic_space_info=topic_space_payload,
        )
        wait_for_terminal_state(poller, **kwargs)
        logger.info("Created topic space '%s' on namespace '%s'.", topic_space_name, eg_ctx.namespace_name)

        return {
            "name": topic_space_name,
            "topicTemplates": topic_templates,
            "scopeId": instance_name,
        }

    def _setup_eg_permission_bindings(
        self,
        eg_ctx: EgNamespaceContext,
        instance_resource_id: str,
        topic_space_name: str,
        eg_client_group: Optional[str] = None,
        **kwargs,
    ) -> Dict:
        """Create or confirm publisher and subscriber permission bindings for the topic space.

        Uses GET-then-PUT for each binding to report accurate status. The client group
        defaults to '$all' if not specified.
        """
        client_group = eg_client_group or MGMT_ACTIONS_DEFAULT_EG_CLIENT_GROUP
        pub_name = get_mgmt_actions_resource_name("pub", instance_resource_id)
        sub_name = get_mgmt_actions_resource_name("sub", instance_resource_id)

        result: Dict = {}
        for binding_name, permission, key in [
            (pub_name, "Publisher", "publisher"),
            (sub_name, "Subscriber", "subscriber"),
        ]:
            # Check if binding already exists
            try:
                self.eventgrid_mgmt_client.permission_bindings.get(
                    resource_group_name=eg_ctx.resource_group_name,
                    namespace_name=eg_ctx.namespace_name,
                    permission_binding_name=binding_name,
                )
                logger.info(
                    "Permission binding '%s' already exists on namespace '%s'.",
                    binding_name,
                    eg_ctx.namespace_name,
                )
                result[key] = {"name": binding_name, "clientGroup": client_group}
                continue
            except ResourceNotFoundError:
                pass

            # Create the permission binding
            binding_payload = {
                "properties": {
                    "clientGroupName": client_group,
                    "permission": permission,
                    "topicSpaceName": topic_space_name,
                    "description": (
                        f"Management actions {permission.lower()} binding " f"for topic space '{topic_space_name}'."
                    ),
                }
            }

            poller = self.eventgrid_mgmt_client.permission_bindings.begin_create_or_update(
                resource_group_name=eg_ctx.resource_group_name,
                namespace_name=eg_ctx.namespace_name,
                permission_binding_name=binding_name,
                permission_binding_info=binding_payload,
            )
            wait_for_terminal_state(poller, **kwargs)
            logger.info(
                "Created permission binding '%s' (%s) on namespace '%s'.",
                binding_name,
                permission,
                eg_ctx.namespace_name,
            )
            result[key] = {"name": binding_name, "clientGroup": client_group}

        return result

    def _setup_eg_dataflow_endpoint(
        self,
        eg_ctx: EgNamespaceContext,
        instance_name: str,
        instance_resource_id: str,
        resource_group_name: str,
        extended_location: Dict,
        mi_resource: Optional[Dict] = None,
        **kwargs,
    ) -> Dict:
        """Create or confirm the EG MQTT dataflow endpoint on the AIO instance.

        Uses GET-then-PUT to report accurate status. The endpoint connects to the EG
        namespace's MQTT broker using managed identity authentication. Defaults to
        SystemAssigned MI; when mi_resource is provided, a UserAssigned MI is
        configured instead using clientId and tenantId from the resolved UAMI resource.
        """
        endpoint_name = get_mgmt_actions_resource_name("eg", instance_resource_id)

        # Check if endpoint already exists
        try:
            existing = self.iotops_mgmt_client.dataflow_endpoint.get(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_endpoint_name=endpoint_name,
            )
            logger.info(
                "Dataflow endpoint '%s' already exists on instance '%s'.",
                endpoint_name,
                instance_name,
            )
            existing_auth = existing.get("properties", {}).get("mqttSettings", {}).get("authentication", {})
            return {"name": endpoint_name, "authentication": existing_auth}
        except ResourceNotFoundError:
            pass

        # Build authentication block
        if mi_resource:
            authentication = {
                "method": "UserAssignedManagedIdentity",
                "userAssignedManagedIdentitySettings": {
                    "clientId": mi_resource["properties"]["clientId"],
                    "tenantId": mi_resource["properties"]["tenantId"],
                    "scope": MGMT_ACTIONS_EG_AUDIENCE,
                },
            }
        else:
            authentication = {
                "method": "SystemAssignedManagedIdentity",
                "systemAssignedManagedIdentitySettings": {
                    "audience": MGMT_ACTIONS_EG_AUDIENCE,
                },
            }

        resource = {
            "extendedLocation": extended_location,
            "properties": {
                "endpointType": MQTT_ENDPOINT_TYPE,
                "mqttSettings": {
                    "host": eg_ctx.mqtt_hostname,
                    "authentication": authentication,
                    "tls": {
                        "mode": "Enabled",
                    },
                },
            },
        }

        poller = self.iotops_mgmt_client.dataflow_endpoint.begin_create_or_update(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_endpoint_name=endpoint_name,
            resource=resource,
        )
        wait_for_terminal_state(poller, **kwargs)
        logger.info(
            "Created dataflow endpoint '%s' on instance '%s'.",
            endpoint_name,
            instance_name,
        )

        return {"name": endpoint_name, "authentication": authentication}

    def _setup_adr_management_endpoint(
        self,
        instance: Dict,
        eg_ctx: EgNamespaceContext,
        **kwargs,
    ) -> Dict:
        """Enable system-assigned MI and configure the management endpoint on the ADR namespace.

        Performs a GET-merge-PUT to preserve existing management endpoints. The endpoint
        key is the instance's custom location resource ID, connecting the ADR namespace
        to the Event Grid MQTT broker for management actions routing.

        Returns a dict with the ADR namespace identity state and the full management
        endpoints map (all custom location entries, not just ours) for multi-instance
        awareness.
        """
        # Resolve ADR namespace from instance
        adr_namespace_resource_id = instance.get("properties", {}).get("adrNamespaceRef", {}).get("resourceId")
        if not adr_namespace_resource_id:
            raise ValidationError(
                "Instance does not have an ADR namespace reference (adrNamespaceRef.resourceId). "
                "This is required for management actions. Ensure the instance was deployed with an ADR namespace."
            )

        parsed_adr = parse_resource_id_dict(adr_namespace_resource_id)
        adr_resource_group = parsed_adr.get("resource_group", "")
        adr_namespace_name = parsed_adr.get("name", "")

        if not all([adr_resource_group, adr_namespace_name]):
            raise ValidationError(
                f"Malformed ADR namespace resource Id '{adr_namespace_resource_id}'. "
                f"Could not extract resource group or namespace name."
            )

        # GET the ADR namespace
        adr_namespace = self.registry_mgmt_client.namespaces.get(
            resource_group_name=adr_resource_group,
            namespace_name=adr_namespace_name,
        )

        # Determine identity state and whether an update is needed
        current_identity = adr_namespace.get("identity", {})
        current_identity_type = (current_identity.get("type") or "").lower()
        identity_already_enabled = current_identity_type == "systemassigned"

        # Build management endpoint entry — keyed by custom location resource ID
        custom_location_id: str = instance["extendedLocation"]["name"]
        desired_endpoint = {
            "endpointType": MGMT_ACTIONS_ADR_ENDPOINT_TYPE,
            "address": eg_ctx.mqtt_hostname,
            "scopeId": instance.get("name", ""),
            "resourceId": eg_ctx.resource_id,
        }

        # Read existing management endpoints (GET-merge-PUT to preserve other entries)
        existing_endpoints = adr_namespace.get("properties", {}).get("management", {}).get("endpoints", {})
        current_endpoint = existing_endpoints.get(custom_location_id)
        endpoint_already_configured = current_endpoint == desired_endpoint

        # Skip update entirely if both identity and endpoint are already correct
        if identity_already_enabled and endpoint_already_configured:
            principal_id = current_identity.get("principalId", "")
            logger.info(
                "ADR namespace '%s' already has SystemAssigned identity and management endpoint configured.",
                adr_namespace_name,
            )
            return {
                "name": adr_namespace_name,
                "identity": {
                    "type": current_identity.get("type", ""),
                    "principalId": principal_id,
                },
                "managementEndpoints": existing_endpoints,
            }

        # Build the update payload
        merged_endpoints = dict(existing_endpoints)
        merged_endpoints[custom_location_id] = desired_endpoint

        update_payload: Dict = {
            "properties": {
                "management": {
                    "endpoints": merged_endpoints,
                },
            },
        }

        # Always include identity in the update to ensure SystemAssigned is set
        if not identity_already_enabled:
            update_payload["identity"] = {"type": "SystemAssigned"}

        poller = self.registry_mgmt_client.namespaces.begin_update(
            resource_group_name=adr_resource_group,
            namespace_name=adr_namespace_name,
            properties=update_payload,
        )
        updated_namespace = wait_for_terminal_state(poller, **kwargs)

        principal_id = updated_namespace.get("identity", {}).get("principalId", "")
        if not principal_id:
            raise ValidationError(
                f"ADR namespace '{adr_namespace_name}' was updated with SystemAssigned identity "
                f"but no principalId was returned. This may indicate the operation is still propagating."
            )

        updated_identity = updated_namespace.get("identity", {})
        updated_endpoints = updated_namespace.get("properties", {}).get("management", {}).get("endpoints", {})

        logger.info(
            "ADR namespace '%s' updated — identity type: %s, management endpoints: %d.",
            adr_namespace_name,
            updated_identity.get("type", ""),
            len(updated_endpoints),
        )

        return {
            "name": adr_namespace_name,
            "identity": {
                "type": updated_identity.get("type", ""),
                "principalId": principal_id,
            },
            "managementEndpoints": updated_endpoints,
        }

    def _setup_dataflow_graph(
        self,
        instance_name: str,
        instance_resource_id: str,
        resource_group_name: str,
        extended_location: Dict,
        eg_dataflow_endpoint_name: str,
        dataflow_profile_name: str,
        **kwargs,
    ) -> Dict:
        """Create or confirm the management actions dataflow graph on the AIO instance.

        The graph wires MQTT request messages through a graph-dataflow-map rules engine
        and back to a local MQTT destination. Three nodes (Source → Graph → Destination)
        with two connections form the pipeline.
        """
        graph_name = get_mgmt_actions_resource_name("req", instance_resource_id)

        # Check if dataflow graph already exists
        try:
            self.iotops_mgmt_client.dataflow_graph.get(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_profile_name=dataflow_profile_name,
                dataflow_graph_name=graph_name,
            )
            logger.info(
                "Dataflow graph '%s' already exists on instance '%s'.",
                graph_name,
                instance_name,
            )
            return {"name": graph_name}
        except ResourceNotFoundError:
            pass

        request_topic_prefix = f"actions/requests/{instance_name}/"
        rules_config = _build_graph_rules_config(
            topic_prefix_regex=f"^{request_topic_prefix}",
        )

        resource = {
            "extendedLocation": extended_location,
            "properties": {
                "mode": "Enabled",
                "nodes": [
                    {
                        "name": "source",
                        "nodeType": "Source",
                        "sourceSettings": {
                            "endpointRef": eg_dataflow_endpoint_name,
                            "dataSources": [f"{request_topic_prefix}#"],
                        },
                    },
                    {
                        "name": "graph",
                        "nodeType": "Graph",
                        "graphSettings": {
                            "registryEndpointRef": MGMT_ACTIONS_DEFAULT_REGISTRY_ENDPOINT,
                            "artifact": MGMT_ACTIONS_GRAPH_ARTIFACT,
                            "configuration": rules_config,
                        },
                    },
                    {
                        "name": "destination",
                        "nodeType": "Destination",
                        "destinationSettings": {
                            "endpointRef": MGMT_ACTIONS_DEFAULT_MQTT_ENDPOINT,
                            "dataDestination": "${outputTopic}",
                        },
                    },
                ],
                "nodeConnections": [
                    {
                        "from": {"name": "source"},
                        "to": {"name": "graph"},
                    },
                    {
                        "from": {"name": "graph"},
                        "to": {"name": "destination"},
                    },
                ],
            },
        }

        poller = self.iotops_mgmt_client.dataflow_graph.begin_create_or_update(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_profile_name=dataflow_profile_name,
            dataflow_graph_name=graph_name,
            resource=resource,
        )
        wait_for_terminal_state(poller, **kwargs)
        logger.info(
            "Created dataflow graph '%s' on instance '%s' (profile: '%s').",
            graph_name,
            instance_name,
            dataflow_profile_name,
        )

        return {"name": graph_name}

    def _setup_response_dataflow(
        self,
        instance_name: str,
        instance_resource_id: str,
        resource_group_name: str,
        extended_location: Dict,
        eg_dataflow_endpoint_name: str,
        dataflow_profile_name: str,
        **kwargs,
    ) -> Dict:
        """Create or confirm the management actions response dataflow on the AIO instance.

        Routes response messages from the local MQTT broker back to Event Grid.
        This is a simple source→destination pipeline (not a graph) — responses don't
        require topic transformation because they already carry the full topic path.
        """
        dataflow_name = get_mgmt_actions_resource_name("resp", instance_resource_id)

        # Check if response dataflow already exists
        try:
            self.iotops_mgmt_client.dataflow.get(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_profile_name=dataflow_profile_name,
                dataflow_name=dataflow_name,
            )
            logger.info(
                "Response dataflow '%s' already exists on instance '%s'.",
                dataflow_name,
                instance_name,
            )
            return {"name": dataflow_name}
        except ResourceNotFoundError:
            pass

        response_topic = MGMT_ACTIONS_RESPONSE_TOPIC_TEMPLATE.format(scope_id=instance_name)

        resource = {
            "extendedLocation": extended_location,
            "properties": {
                "mode": "Enabled",
                "operations": [
                    {
                        "operationType": "Source",
                        "sourceSettings": {
                            "endpointRef": MGMT_ACTIONS_DEFAULT_MQTT_ENDPOINT,
                            "dataSources": [response_topic],
                        },
                    },
                    {
                        "operationType": "Destination",
                        "destinationSettings": {
                            "endpointRef": eg_dataflow_endpoint_name,
                            "dataDestination": "${inputTopic}",
                        },
                    },
                ],
            },
        }

        poller = self.iotops_mgmt_client.dataflow.begin_create_or_update(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_profile_name=dataflow_profile_name,
            dataflow_name=dataflow_name,
            resource=resource,
        )
        wait_for_terminal_state(poller, **kwargs)
        logger.info(
            "Created response dataflow '%s' on instance '%s' (profile: '%s').",
            dataflow_name,
            instance_name,
            dataflow_profile_name,
        )

        return {"name": dataflow_name}

    def _resolve_user_assigned_mi(self, mi_resource_id: str) -> Dict:
        """Fetch a user-assigned managed identity resource to extract clientId and tenantId.

        Uses the base Queryable resource_client for same-subscription lookups. When the
        UAMI is in a different subscription, creates a cross-subscription client.
        """
        parsed = parse_resource_id_dict(mi_resource_id)
        mi_subscription = parsed.get("subscription", self.default_subscription_id)

        if mi_subscription.lower() != self.default_subscription_id.lower():
            from ...util.az_client import get_resource_client

            client = get_resource_client(subscription_id=mi_subscription)
        else:
            client = self.resource_client

        try:
            return client.resources.get_by_id(
                resource_id=mi_resource_id,
                api_version=MANAGED_IDENTITY_API_VERSION,
            )
        except ResourceNotFoundError:
            raise InvalidArgumentValueError(
                f"User-assigned managed identity '{mi_resource_id}' not found.\n"
                f"Verify the --mi-user-assigned value and ensure the identity exists."
            )

    def _resolve_dataflow_auth_identity(
        self,
        instance: Dict,
        mi_resource: Optional[Dict] = None,
    ) -> str:
        """Resolve the principal ID of the identity that authenticates the dataflow endpoint.

        When a UAMI is provided, its principalId is used directly. Otherwise, resolves the
        AIO extension's system MI by traversing: instance → custom location → connected
        cluster → extensions. The resolved principal ID is used for EG role assignments.
        """
        if mi_resource:
            principal_id = mi_resource.get("properties", {}).get("principalId")
            if not principal_id:
                raise ValidationError(
                    "User-assigned managed identity is missing 'principalId'.\n"
                    "Verify the identity resource has been fully provisioned."
                )
            return principal_id

        # Resolve AIO extension system MI via custom location → connected cluster
        cl_id = instance.get("extendedLocation", {}).get("name")
        if not cl_id:
            raise ValidationError(
                "Instance is missing 'extendedLocation.name' (custom location ID).\n"
                "The instance may not be fully provisioned."
            )

        custom_location = self.resource_client.resources.get_by_id(
            resource_id=cl_id,
            api_version=CUSTOM_LOCATIONS_API_VERSION,
        )

        host_resource_id = custom_location.get("properties", {}).get("hostResourceId")
        if not host_resource_id:
            raise ValidationError(
                f"Custom location '{cl_id}' is missing 'hostResourceId'.\n"
                "Unable to resolve the connected cluster for extension identity."
            )

        cluster_parts = parse_resource_id_dict(host_resource_id)
        connected_cluster = ConnectedCluster(
            cmd=self.cmd,
            subscription_id=cluster_parts.get("subscription", self.default_subscription_id),
            cluster_name=cluster_parts["name"],
            resource_group_name=cluster_parts["resource_group"],
        )

        ext_map = connected_cluster.get_extensions_by_type(EXTENSION_TYPE_OPS)
        ops_ext = ext_map.get(EXTENSION_TYPE_OPS)
        if not ops_ext:
            raise ValidationError(
                "IoT Operations extension not found on the connected cluster.\n"
                "Cannot resolve the extension identity for EG role assignments.\n"
                "Ensure 'az iot ops create' has been run successfully."
            )

        principal_id = ops_ext.get("identity", {}).get("principalId")
        if not principal_id:
            raise ValidationError(
                "IoT Operations extension is missing 'identity.principalId'.\n"
                "Cannot assign EG roles without the extension identity.\n"
                "Please re-deploy via 'az iot ops create'."
            )

        return principal_id

    def _setup_role_assignments(
        self,
        eg_ctx: EgNamespaceContext,
        adr_principal_id: str,
        dataflow_auth_principal_id: str,
        adr_role_ids: Optional[List[str]] = None,
        ops_role_ids: Optional[List[str]] = None,
    ) -> Dict:
        """Assign EG Topic Spaces Publisher/Subscriber roles for both identity principals.

        Two principals need EG namespace access:
        - ADR namespace system MI (for device registry ↔ EG communication)
        - Dataflow auth identity (for dataflow endpoint ↔ EG communication)

        Uses a separate PermissionManager when the EG namespace is in a different
        subscription than the instance. Role assignments are idempotent — existing
        assignments are skipped.
        """
        default_role_ids = [EG_TOPICSPACES_PUBLISHER_ROLE_ID, EG_TOPICSPACES_SUBSCRIBER_ROLE_ID]
        resolved_adr_roles = adr_role_ids or default_role_ids
        resolved_ops_roles = ops_role_ids or default_role_ids

        # Use a cross-subscription PermissionManager when the EG namespace lives
        # in a different subscription than the instance.
        if eg_ctx.subscription_id.lower() != self.default_subscription_id.lower():
            eg_permission_manager = PermissionManager(subscription_id=eg_ctx.subscription_id)
        else:
            eg_permission_manager = self.permission_manager

        scope = eg_ctx.resource_id

        identity_assignments = [
            ("adrNamespace", adr_principal_id, resolved_adr_roles),
            ("dataflowIdentity", dataflow_auth_principal_id, resolved_ops_roles),
        ]

        result: Dict = {}
        for result_key, principal_id, role_ids in identity_assignments:
            try:
                for role_id in role_ids:
                    role_def_id = ROLE_DEF_FORMAT_STR.format(
                        subscription_id=eg_ctx.subscription_id,
                        role_id=role_id,
                    )
                    eg_permission_manager.apply_role_assignment(
                        scope=scope,
                        principal_id=principal_id,
                        role_def_id=role_def_id,
                        principal_type=PrincipalType.SERVICE_PRINCIPAL.value,
                    )
            except HttpResponseError as e:
                raise ValidationError(
                    f"Failed to assign role(s) for principal '{principal_id}' "
                    f"on EG namespace '{eg_ctx.namespace_name}'.\n"
                    f"Error: {e.message}\n"
                    f"You can manually assign the required roles:\n"
                    f"  Scope: {scope}\n"
                    f"  Principal ID: {principal_id}\n"
                    f"  Role IDs: {', '.join(role_ids)}"
                )

            result[result_key] = {
                "principalId": principal_id,
                "roles": list(role_ids),
            }

        return result
