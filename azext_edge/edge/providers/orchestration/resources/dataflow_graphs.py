# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from typing import TYPE_CHECKING, Iterable, Optional

from rich.console import Console

from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.exceptions import ResourceNotFoundError

from ....util.az_client import wait_for_terminal_state
from ....util.common import should_continue_prompt
from ....util.queryable import Queryable
from ..common import DataflowEndpointType, KAFKA_ENDPOINT_TYPE, MQTT_ENDPOINT_TYPE
from .instances import Instances
from .reskit import get_file_config

console = Console()

# Endpoint types supported in data flow graphs (MQTT family + Kafka family + OpenTelemetry).
# DataExplorer, DataLakeStorage, FabricOneLake, LocalStorage are not supported.
_GRAPH_SUPPORTED_ENDPOINT_TYPES = frozenset([
    # MQTT family
    DataflowEndpointType.AIOLOCALMQTT.value,
    DataflowEndpointType.EVENTGRID.value,
    DataflowEndpointType.CUSTOMMQTT.value,
    MQTT_ENDPOINT_TYPE,  # legacy generic Mqtt type
    # Kafka family
    DataflowEndpointType.EVENTHUB.value,
    DataflowEndpointType.FABRICREALTIME.value,
    DataflowEndpointType.CUSTOMKAFKA.value,
    KAFKA_ENDPOINT_TYPE,  # legacy generic Kafka type
    # OpenTelemetry
    DataflowEndpointType.OPENTELEMETRY.value,
])
# Destination-only endpoint types (cannot be used as a source node).
_DESTINATION_ONLY_ENDPOINT_TYPES = frozenset([
    DataflowEndpointType.FABRICREALTIME.value,
    DataflowEndpointType.OPENTELEMETRY.value,
])
# Valid node types in a dataflow graph config.
_VALID_NODE_TYPES = frozenset(["Source", "Graph", "Destination"])


if TYPE_CHECKING:
    from ....vendor.clients.iotopsmgmt.operations import (
        DataflowEndpointOperations,
        DataflowGraphOperations,
        RegistryEndpointOperations,
    )


class DataFlowGraphs(Queryable):
    def __init__(self, cmd):
        super().__init__(cmd=cmd)
        self.instances = Instances(cmd=cmd)
        self.iotops_mgmt_client = self.instances.iotops_mgmt_client
        self.ops: "DataflowGraphOperations" = self.iotops_mgmt_client.dataflow_graph
        self.ops_endpoint: "DataflowEndpointOperations" = self.iotops_mgmt_client.dataflow_endpoint
        self.ops_registry_endpoint: "RegistryEndpointOperations" = self.iotops_mgmt_client.registry_endpoint

    def show(
        self,
        name: str,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
    ) -> dict:
        return self.ops.get(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_profile_name=dataflow_profile_name,
            dataflow_graph_name=name,
        )

    def list(
        self,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
    ) -> Iterable[dict]:
        return self.ops.list_by_dataflow_profile(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_profile_name=dataflow_profile_name,
        )

    def apply(
        self,
        name: str,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
        config_file: str,
        **kwargs,
    ) -> dict:
        resource = {}
        graph_config = get_file_config(config_file)

        self._validate_graph_config(graph_config, instance_name, resource_group_name)

        resource["extendedLocation"] = self.instances.get_ext_loc(
            name=instance_name,
            resource_group_name=resource_group_name,
        )
        resource["properties"] = graph_config

        with console.status("Working..."):
            poller = self.ops.begin_create_or_update(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_profile_name=dataflow_profile_name,
                dataflow_graph_name=name,
                resource=resource,
            )
            return wait_for_terminal_state(poller, **kwargs)

    def _validate_graph_config(
        self,
        graph_config: dict,
        instance_name: str,
        resource_group_name: str,
    ):
        nodes, declared_names = self._validate_nodes(graph_config)

        source_nodes = [n for n in nodes if n.get("nodeType") == "Source"]
        destination_nodes = [n for n in nodes if n.get("nodeType") == "Destination"]
        graph_nodes = [n for n in nodes if n.get("nodeType") == "Graph"]

        if not source_nodes:
            raise InvalidArgumentValueError(
                "The dataflow graph config must contain at least one node with nodeType 'Source'."
            )
        if not destination_nodes:
            raise InvalidArgumentValueError(
                "The dataflow graph config must contain at least one node with nodeType 'Destination'."
            )

        self._validate_node_connections(graph_config, declared_names)

        endpoint_cache: dict = {}

        def get_endpoint_cached(endpoint_ref: str) -> dict:
            if endpoint_ref not in endpoint_cache:
                endpoint_cache[endpoint_ref] = self._get_endpoint(
                    endpoint_ref, instance_name, resource_group_name
                )
            return endpoint_cache[endpoint_ref]

        self._validate_source_nodes(source_nodes, get_endpoint_cached)
        self._validate_destination_nodes(destination_nodes, get_endpoint_cached)

        registry_endpoint_cache: dict = {}

        def get_registry_endpoint_cached(registry_endpoint_ref: str) -> dict:
            if registry_endpoint_ref not in registry_endpoint_cache:
                registry_endpoint_cache[registry_endpoint_ref] = self._get_registry_endpoint(
                    registry_endpoint_ref, instance_name, resource_group_name
                )
            return registry_endpoint_cache[registry_endpoint_ref]

        self._validate_graph_nodes(graph_nodes, get_registry_endpoint_cached)

    def _validate_nodes(self, graph_config: dict):
        nodes = graph_config.get("nodes", [])
        if not isinstance(nodes, list) or not nodes:
            raise InvalidArgumentValueError(
                "'nodes' is required and must contain at least one node in the dataflow graph config."
            )

        declared_names = set()
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                raise InvalidArgumentValueError(
                    f"Node at index {i} must be an object, got {type(node).__name__}."
                )
            node_name = node.get("name", "")
            node_type = node.get("nodeType", "")

            if not node_name:
                raise InvalidArgumentValueError(
                    f"Node at index {i} is missing a 'name'."
                )
            if not node_type:
                raise InvalidArgumentValueError(
                    f"Node '{node_name}' is missing a 'nodeType'."
                )
            if node_type not in _VALID_NODE_TYPES:
                raise InvalidArgumentValueError(
                    f"Node '{node_name}' has invalid nodeType '{node_type}'. "
                    f"Valid nodeType values are: {', '.join(sorted(_VALID_NODE_TYPES))}."
                )
            if node_name in declared_names:
                raise InvalidArgumentValueError(
                    f"Duplicate node name '{node_name}' found at index {i}. "
                    "Each node in the dataflow graph config must have a unique 'name'."
                )
            declared_names.add(node_name)

        return nodes, declared_names

    def _validate_node_connections(self, graph_config: dict, declared_names: set):
        node_connections = graph_config.get("nodeConnections", [])
        if not isinstance(node_connections, list) or not node_connections:
            raise InvalidArgumentValueError(
                "'nodeConnections' is required and must contain at least one connection in the dataflow graph config."
            )
        for i, conn in enumerate(node_connections):
            if not isinstance(conn, dict):
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} must be an object, got {type(conn).__name__}."
                )
            from_val = conn.get("from")
            to_val = conn.get("to")
            if not isinstance(from_val, dict) or not from_val.get("name"):
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} is missing a valid 'from.name' field."
                )
            if not isinstance(to_val, dict) or not to_val.get("name"):
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} is missing a valid 'to.name' field."
                )
            from_name = from_val["name"]
            to_name = to_val["name"]
            if from_name == to_name:
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} is a self-loop: 'from' and 'to' both reference node '{from_name}'."
                )
            if from_name not in declared_names:
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} references unknown 'from' node '{from_name}'. "
                    f"Declared node names: {', '.join(sorted(declared_names))}."
                )
            if to_name not in declared_names:
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} references unknown 'to' node '{to_name}'. "
                    f"Declared node names: {', '.join(sorted(declared_names))}."
                )

    def _validate_source_nodes(self, source_nodes: list, get_endpoint_cached):
        kafka_types = {DataflowEndpointType.EVENTHUB.value, DataflowEndpointType.CUSTOMKAFKA.value, KAFKA_ENDPOINT_TYPE}
        for node in source_nodes:
            source_settings = node.get("sourceSettings", {})
            if not isinstance(source_settings, dict):
                raise InvalidArgumentValueError(
                    f"Source node '{node.get('name')}' has an invalid 'sourceSettings' field: "
                    f"expected an object, got {type(source_settings).__name__}."
                )
            endpoint_ref = source_settings.get("endpointRef", "")
            if not endpoint_ref:
                raise InvalidArgumentValueError(
                    f"Source node '{node.get('name')}' is missing 'sourceSettings.endpointRef'."
                )
            endpoint_obj = get_endpoint_cached(endpoint_ref)
            endpoint_props = endpoint_obj.get("properties", {})
            endpoint_type = endpoint_props.get("endpointType", "")

            if endpoint_type and endpoint_type not in _GRAPH_SUPPORTED_ENDPOINT_TYPES:
                raise InvalidArgumentValueError(
                    f"Source node '{node.get('name')}' references endpoint '{endpoint_ref}' "
                    f"of type '{endpoint_type}', which is not supported in data flow graphs. "
                    f"Supported endpoint types are: "
                    f"{', '.join(sorted(_GRAPH_SUPPORTED_ENDPOINT_TYPES))}."
                )
            if endpoint_type in _DESTINATION_ONLY_ENDPOINT_TYPES:
                raise InvalidArgumentValueError(
                    f"Source node '{node.get('name')}' references endpoint '{endpoint_ref}' "
                    f"of type '{endpoint_type}', which is destination-only and cannot be used as a source."
                )

            if endpoint_type in kafka_types:
                kafka_settings = endpoint_props.get("kafkaSettings") or {}
                if not kafka_settings.get("consumerGroupId", ""):
                    raise InvalidArgumentValueError(
                        f"Source node '{node.get('name')}' references Kafka endpoint '{endpoint_ref}', "
                        f"but the endpoint does not have 'kafkaSettings.consumerGroupId' set. "
                        f"A consumer group ID is required for Kafka source endpoints."
                    )

    def _validate_destination_nodes(self, destination_nodes: list, get_endpoint_cached):
        for node in destination_nodes:
            dest_settings = node.get("destinationSettings", {})
            if not isinstance(dest_settings, dict):
                raise InvalidArgumentValueError(
                    f"Destination node '{node.get('name')}' has an invalid 'destinationSettings' field: "
                    f"expected an object, got {type(dest_settings).__name__}."
                )
            endpoint_ref = dest_settings.get("endpointRef", "")
            if not endpoint_ref:
                raise InvalidArgumentValueError(
                    f"Destination node '{node.get('name')}' is missing 'destinationSettings.endpointRef'."
                )
            endpoint_obj = get_endpoint_cached(endpoint_ref)
            endpoint_type = endpoint_obj.get("properties", {}).get("endpointType", "")

            if endpoint_type and endpoint_type not in _GRAPH_SUPPORTED_ENDPOINT_TYPES:
                raise InvalidArgumentValueError(
                    f"Destination node '{node.get('name')}' references endpoint '{endpoint_ref}' "
                    f"of type '{endpoint_type}', which is not supported in data flow graphs. "
                    f"Supported endpoint types are: "
                    f"{', '.join(sorted(_GRAPH_SUPPORTED_ENDPOINT_TYPES))}."
                )

    def _validate_graph_nodes(self, graph_nodes: list, get_registry_endpoint_cached):
        for node in graph_nodes:
            graph_settings = node.get("graphSettings", {})
            if not isinstance(graph_settings, dict):
                raise InvalidArgumentValueError(
                    f"Graph node '{node.get('name')}' has an invalid 'graphSettings' field: "
                    f"expected an object, got {type(graph_settings).__name__}."
                )
            registry_endpoint_ref = graph_settings.get("registryEndpointRef", "")
            if not registry_endpoint_ref:
                raise InvalidArgumentValueError(
                    f"Graph node '{node.get('name')}' is missing 'graphSettings.registryEndpointRef'."
                )
            get_registry_endpoint_cached(registry_endpoint_ref)
            artifact = graph_settings.get("artifact", "")
            if not artifact:
                raise InvalidArgumentValueError(
                    f"Graph node '{node.get('name')}' is missing 'graphSettings.artifact'."
                )
            if ":" not in artifact or artifact.startswith(":") or artifact.endswith(":"):
                raise InvalidArgumentValueError(
                    f"Graph node '{node.get('name')}' has an invalid 'graphSettings.artifact' value '{artifact}'. "
                    "Expected format: '<artifact-name>:<version>'."
                )

    def _get_endpoint(
        self,
        endpoint_name: str,
        instance_name: str,
        resource_group_name: str,
    ) -> dict:
        """Fetch a dataflow endpoint by name, raising a clear error if not found."""
        try:
            return self.ops_endpoint.get(
                instance_name=instance_name,
                resource_group_name=resource_group_name,
                dataflow_endpoint_name=endpoint_name,
            )
        except ResourceNotFoundError:
            raise ResourceNotFoundError(
                f"Dataflow endpoint '{endpoint_name}' not found in instance '{instance_name}'. "
                "Please provide a valid 'endpointRef' using --config-file."
            )

    def _get_registry_endpoint(
        self,
        registry_endpoint_name: str,
        instance_name: str,
        resource_group_name: str,
    ) -> dict:
        """Fetch a registry endpoint by name, raising a clear error if not found."""
        try:
            return self.ops_registry_endpoint.get(
                instance_name=instance_name,
                resource_group_name=resource_group_name,
                registry_endpoint_name=registry_endpoint_name,
            )
        except ResourceNotFoundError:
            raise ResourceNotFoundError(
                f"Registry endpoint '{registry_endpoint_name}' not found in instance '{instance_name}'. "
                "Please provide a valid 'registryEndpointRef' using --config-file."
            )

    def delete(
        self,
        name: str,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
        confirm_yes: Optional[bool] = None,
        **kwargs,
    ):
        should_bail = not should_continue_prompt(confirm_yes=confirm_yes)
        if should_bail:
            return

        with console.status("Working..."):
            poller = self.ops.begin_delete(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_profile_name=dataflow_profile_name,
                dataflow_graph_name=name,
            )
            return wait_for_terminal_state(poller, **kwargs)
