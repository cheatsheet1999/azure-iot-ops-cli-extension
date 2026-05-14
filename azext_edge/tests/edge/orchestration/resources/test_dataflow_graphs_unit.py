# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import json
from typing import Optional
from unittest.mock import Mock

import pytest
import responses

from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.exceptions import ResourceNotFoundError

from azext_edge.edge.commands_dataflowgraph import (
    apply_dataflow_graph,
    delete_dataflow_graph,
    list_dataflow_graphs,
    show_dataflow_graph,
)
from .dataflow_endpoint.conftest import (
    get_dataflow_endpoint_endpoint,
    get_mock_dataflow_endpoint_record,
)
from .test_instances_unit import (
    get_instance_endpoint,
    get_mock_instance_record,
)
from .registry_endpoint.test_registry_endpoints_unit import (
    get_registry_endpoint_endpoint,
    get_mock_registry_endpoint_record,
)
from ....generators import generate_random_string
from .conftest import get_base_endpoint, get_mock_resource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_dataflow_graph_endpoint(
    profile_name: str,
    instance_name: str,
    resource_group_name: str,
    graph_name: Optional[str] = None,
    **kwargs,
) -> str:
    resource_path = f"/instances/{instance_name}/dataflowProfiles/{profile_name}/dataflowGraphs"
    if graph_name:
        resource_path += f"/{graph_name}"
    return get_base_endpoint(resource_group_name=resource_group_name, resource_path=resource_path, **kwargs)


def get_mock_dataflow_graph_record(
    graph_name: str,
    profile_name: str,
    instance_name: str,
    resource_group_name: str,
    extra_nodes: Optional[list] = None,
) -> dict:
    nodes = [
        {
            "name": "source-node",
            "nodeType": "Source",
            "sourceSettings": {
                "endpointRef": "myendpoint1",
                "dataSources": ["test/topic"],
            },
        },
        {
            "name": "dest-node",
            "nodeType": "Destination",
            "destinationSettings": {
                "endpointRef": "myendpoint2",
                "dataDestination": "output/topic",
            },
        },
    ]
    if extra_nodes:
        nodes.extend(extra_nodes)

    properties = {
        "nodes": nodes,
        "nodeConnections": [
            {"from": {"name": "source-node"}, "to": {"name": "dest-node"}}
        ],
        "provisioningState": "Succeeded",
    }
    return get_mock_resource(
        name=graph_name,
        resource_path=(
            f"/instances/{instance_name}/dataflowProfiles/{profile_name}/dataflowGraphs/{graph_name}"
        ),
        properties=properties,
        resource_group_name=resource_group_name,
        qualified_type="microsoft.iotoperations/instances/dataflowgraphs",
        is_proxy_resource=True,
    )


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_dataflow_graph_show(mocked_cmd, mocked_responses: responses):
    graph_name = generate_random_string()
    profile_name = generate_random_string()
    instance_name = generate_random_string()
    resource_group_name = generate_random_string()

    mock_record = get_mock_dataflow_graph_record(
        graph_name=graph_name,
        profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
    )
    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_graph_endpoint(
            graph_name=graph_name,
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
        ),
        json=mock_record,
        status=200,
        content_type="application/json",
    )

    result = show_dataflow_graph(
        cmd=mocked_cmd,
        dataflow_graph_name=graph_name,
        profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
    )

    assert result == mock_record
    assert len(mocked_responses.calls) == 1


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("records", [0, 2])
def test_dataflow_graph_list(mocked_cmd, mocked_responses: responses, records: int):
    profile_name = generate_random_string()
    instance_name = generate_random_string()
    resource_group_name = generate_random_string()

    mock_records = {
        "value": [
            get_mock_dataflow_graph_record(
                graph_name=generate_random_string(),
                profile_name=profile_name,
                instance_name=instance_name,
                resource_group_name=resource_group_name,
            )
            for _ in range(records)
        ]
    }
    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_graph_endpoint(
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
        ),
        json=mock_records,
        status=200,
        content_type="application/json",
    )

    result = list(
        list_dataflow_graphs(
            cmd=mocked_cmd,
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
        )
    )

    assert result == mock_records["value"]
    assert len(mocked_responses.calls) == 1


# ---------------------------------------------------------------------------
# apply - success
# ---------------------------------------------------------------------------


def test_dataflow_graph_apply_invalid_json_config(
    mocked_cmd,
    mocked_get_file_config: Mock,
):
    mocked_get_file_config.return_value = "bad json {"

    with pytest.raises(InvalidArgumentValueError) as exc:
        apply_dataflow_graph(
            cmd=mocked_cmd,
            dataflow_graph_name=generate_random_string(),
            profile_name=generate_random_string(),
            instance_name=generate_random_string(),
            resource_group_name=generate_random_string(),
            config_file="config.json",
        )

    assert "--config-file" in exc.value.error_msg
    assert "config.json" in exc.value.error_msg


@pytest.mark.parametrize(
    "scenario",
    [
        # MQTT source (AIOLocalMqtt) → MQTT destination (CustomMqtt)
        {
            "source_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint1",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="AIOLocalMqtt",
                host="aio-broker",
            ),
            "destination_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint2",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="CustomMqtt",
            ),
        },
        # Kafka source (EventHub, with consumerGroupId) → MQTT destination (AIOLocalMqtt)
        {
            "source_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint1",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="EventHub",
                group_id="my-consumer-group",
            ),
            "destination_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint2",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="AIOLocalMqtt",
                host="aio-broker",
            ),
        },
        # MQTT source (EventGrid) → OpenTelemetry destination
        {
            "source_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint1",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="EventGrid",
                host="aio-broker",
            ),
            "destination_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint2",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="OpenTelemetry",
            ),
        },
        # MQTT source (AIOLocalMqtt) → Kafka destination (CustomKafka)
        {
            "source_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint1",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="AIOLocalMqtt",
                host="aio-broker",
            ),
            "destination_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint2",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="CustomKafka",
            ),
        },
        # Legacy generic Mqtt source → legacy generic Mqtt destination
        {
            "source_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint1",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="Mqtt",
                host="aio-broker",
            ),
            "destination_endpoint": get_mock_dataflow_endpoint_record(
                dataflow_endpoint_name="myendpoint2",
                instance_name="myinstance",
                resource_group_name="myresourcegroup",
                dataflow_endpoint_type="Mqtt",
            ),
        },
    ],
)
def test_dataflow_graph_apply(
    mocked_cmd,
    mocked_responses: responses,
    mocked_get_file_config: Mock,
    scenario: dict,
):

    graph_name = generate_random_string()
    profile_name = generate_random_string()
    instance_name = "myinstance"
    resource_group_name = "myresourcegroup"

    file_payload = get_mock_dataflow_graph_record(
        graph_name=graph_name,
        profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
    )
    mocked_get_file_config.return_value = json.dumps(file_payload)

    mock_instance_record = get_mock_instance_record(
        name=instance_name, resource_group_name=resource_group_name
    )
    mocked_responses.add(
        method=responses.GET,
        url=get_instance_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
        ),
        json=mock_instance_record,
        status=200,
    )

    source_endpoint = scenario["source_endpoint"]
    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_endpoint_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_endpoint_name=source_endpoint["name"],
        ),
        json=source_endpoint,
        status=200,
    )

    dest_endpoint = scenario["destination_endpoint"]
    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_endpoint_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_endpoint_name=dest_endpoint["name"],
        ),
        json=dest_endpoint,
        status=200,
    )

    put_response = mocked_responses.add(
        method=responses.PUT,
        url=get_dataflow_graph_endpoint(
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            graph_name=graph_name,
        ),
        json=file_payload,
        status=200,
    )

    result = apply_dataflow_graph(
        cmd=mocked_cmd,
        dataflow_graph_name=graph_name,
        profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
        config_file="config.json",
        wait_sec=0.1,
    )

    assert len(mocked_responses.calls) == 4
    assert result == file_payload
    request_payload = json.loads(put_response.calls[0].request.body)
    assert request_payload["extendedLocation"] == mock_instance_record["extendedLocation"]


# ---------------------------------------------------------------------------
# apply - structural validation errors (no endpoint mocks needed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "graph_properties, expected_error_text",
    [
        # Empty nodes list
        (
            {"nodes": [], "nodeConnections": []},
            "'nodes' is required and must contain at least one node",
        ),
        # Missing nodes key
        (
            {"nodeConnections": []},
            "'nodes' is required and must contain at least one node",
        ),
        # Node missing name
        (
            {
                "nodes": [{"nodeType": "Source", "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]}}],
                "nodeConnections": [],
            },
            "is missing a 'name'",
        ),
        # Node missing nodeType
        (
            {
                "nodes": [{"name": "my-node"}],
                "nodeConnections": [],
            },
            "is missing a 'nodeType'",
        ),
        # Node with invalid nodeType
        (
            {
                "nodes": [{"name": "my-node", "nodeType": "Relay"}],
                "nodeConnections": [],
            },
            "has invalid nodeType 'Relay'",
        ),
        # Duplicate node name
        (
            {
                "nodes": [
                    {"name": "dup-node", "nodeType": "Source",
                     "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]}},
                    {"name": "dup-node", "nodeType": "Destination",
                     "destinationSettings": {"endpointRef": "ep2", "dataDestination": "t"}},
                ],
                "nodeConnections": [],
            },
            "Duplicate node name 'dup-node'",
        ),
        # No Source node
        (
            {
                "nodes": [
                    {
                        "name": "dest-node",
                        "nodeType": "Destination",
                        "destinationSettings": {"endpointRef": "ep2", "dataDestination": "t"},
                    }
                ],
                "nodeConnections": [],
            },
            "must contain at least one node with nodeType 'Source'",
        ),
        # No Destination node
        (
            {
                "nodes": [
                    {
                        "name": "src-node",
                        "nodeType": "Source",
                        "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]},
                    }
                ],
                "nodeConnections": [],
            },
            "must contain at least one node with nodeType 'Destination'",
        ),
        # nodeConnection is a self-loop (from == to)
        (
            {
                "nodes": [
                    {"name": "src", "nodeType": "Source",
                     "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]}},
                    {"name": "dst", "nodeType": "Destination",
                     "destinationSettings": {"endpointRef": "ep2", "dataDestination": "t"}},
                ],
                "nodeConnections": [{"from": {"name": "src"}, "to": {"name": "src"}}],
            },
            "is a self-loop",
        ),
        # nodeConnection references unknown 'from' node
        (
            {
                "nodes": [
                    {"name": "src", "nodeType": "Source",
                     "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]}},
                    {"name": "dst", "nodeType": "Destination",
                     "destinationSettings": {"endpointRef": "ep2", "dataDestination": "t"}},
                ],
                "nodeConnections": [{"from": {"name": "ghost"}, "to": {"name": "dst"}}],
            },
            "references unknown 'from' node 'ghost'",
        ),
        # nodeConnection references unknown 'to' node
        (
            {
                "nodes": [
                    {"name": "src", "nodeType": "Source",
                     "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]}},
                    {"name": "dst", "nodeType": "Destination",
                     "destinationSettings": {"endpointRef": "ep2", "dataDestination": "t"}},
                ],
                "nodeConnections": [{"from": {"name": "src"}, "to": {"name": "ghost"}}],
            },
            "references unknown 'to' node 'ghost'",
        ),
        # nodeConnections is not a list (null)
        (
            {
                "nodes": [
                    {"name": "src", "nodeType": "Source",
                     "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]}},
                    {"name": "dst", "nodeType": "Destination",
                     "destinationSettings": {"endpointRef": "ep2", "dataDestination": "t"}},
                ],
                "nodeConnections": None,
            },
            "'nodeConnections' is required and must contain at least one connection",
        ),
        # nodeConnection entry is not a dict
        (
            {
                "nodes": [
                    {"name": "src", "nodeType": "Source",
                     "sourceSettings": {"endpointRef": "ep1", "dataSources": ["t"]}},
                    {"name": "dst", "nodeType": "Destination",
                     "destinationSettings": {"endpointRef": "ep2", "dataDestination": "t"}},
                ],
                "nodeConnections": ["not-a-dict"],
            },
            "nodeConnection at index 0 must be an object",
        ),
    ],
)
def test_dataflow_graph_apply_structural_error(
    mocked_cmd,
    mocked_responses: responses,
    mocked_get_file_config: Mock,
    graph_properties: dict,
    expected_error_text: str,
):
    graph_name = generate_random_string()
    profile_name = generate_random_string()
    instance_name = "myinstance"
    resource_group_name = "myresourcegroup"

    # Wrap in ARM resource so get_file_config extracts properties
    file_payload = {"properties": graph_properties}
    mocked_get_file_config.return_value = json.dumps(file_payload)

    with pytest.raises(InvalidArgumentValueError) as exc:
        apply_dataflow_graph(
            cmd=mocked_cmd,
            dataflow_graph_name=graph_name,
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            config_file="config.json",
            wait_sec=0.1,
        )

    assert expected_error_text in exc.value.args[0]


# ---------------------------------------------------------------------------
# apply - endpoint validation errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario, expected_error_text",
    [
        # Source missing endpointRef
        (
            {
                "graph_properties": {
                    "nodes": [
                        {
                            "name": "src",
                            "nodeType": "Source",
                            "sourceSettings": {"dataSources": ["t"]},  # no endpointRef
                        },
                        {
                            "name": "dst",
                            "nodeType": "Destination",
                            "destinationSettings": {"endpointRef": "myendpoint2", "dataDestination": "t"},
                        },
                    ],
                    "nodeConnections": [{"from": {"name": "src"}, "to": {"name": "dst"}}],
                },
                "source_endpoint": None,
                "destination_endpoint": None,
            },
            "is missing 'sourceSettings.endpointRef'",
        ),
        # Source endpoint not found
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="AIOLocalMqtt",
                    host="aio-broker",
                ),
                "destination_endpoint": None,
                "source_endpoint_status": 404,
                "expected_error_type": ResourceNotFoundError,
            },
            "not found in instance 'myinstance'",
        ),
        # Source endpoint is unsupported type (DataExplorer)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="DataExplorer",
                ),
                "destination_endpoint": None,
            },
            "not supported in data flow graphs",
        ),
        # Source endpoint is unsupported type (DataLakeStorage)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="DataLakeStorage",
                ),
                "destination_endpoint": None,
            },
            "not supported in data flow graphs",
        ),
        # Source endpoint is OpenTelemetry (destination-only)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="OpenTelemetry",
                ),
                "destination_endpoint": None,
            },
            "destination-only and cannot be used as a source",
        ),
        # Source endpoint is FabricRealTime (destination-only)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="FabricRealTime",
                ),
                "destination_endpoint": None,
            },
            "destination-only and cannot be used as a source",
        ),
        # Kafka source missing consumerGroupId (EventHub)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="EventHub",
                    # no group_id → consumerGroupId=""
                ),
                "destination_endpoint": None,
            },
            "A consumer group ID is required for Kafka source endpoints",
        ),
        # Kafka source missing consumerGroupId (CustomKafka)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="CustomKafka",
                    # no group_id → consumerGroupId=""
                ),
                "destination_endpoint": None,
            },
            "A consumer group ID is required for Kafka source endpoints",
        ),
        # Destination missing endpointRef
        (
            {
                "graph_properties": {
                    "nodes": [
                        {
                            "name": "src",
                            "nodeType": "Source",
                            "sourceSettings": {"endpointRef": "myendpoint1", "dataSources": ["t"]},
                        },
                        {
                            "name": "dst",
                            "nodeType": "Destination",
                            "destinationSettings": {"dataDestination": "t"},  # no endpointRef
                        },
                    ],
                    "nodeConnections": [{"from": {"name": "src"}, "to": {"name": "dst"}}],
                },
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="AIOLocalMqtt",
                    host="aio-broker",
                ),
                "destination_endpoint": None,
            },
            "is missing 'destinationSettings.endpointRef'",
        ),
        # Destination endpoint is unsupported type (FabricOneLake)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="AIOLocalMqtt",
                    host="aio-broker",
                ),
                "destination_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint2",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="FabricOneLake",
                ),
            },
            "not supported in data flow graphs",
        ),
        # Destination endpoint is unsupported type (LocalStorage)
        (
            {
                "source_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint1",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="AIOLocalMqtt",
                    host="aio-broker",
                ),
                "destination_endpoint": get_mock_dataflow_endpoint_record(
                    dataflow_endpoint_name="myendpoint2",
                    instance_name="myinstance",
                    resource_group_name="myresourcegroup",
                    dataflow_endpoint_type="LocalStorage",
                ),
            },
            "not supported in data flow graphs",
        ),
    ],
)
def test_dataflow_graph_apply_endpoint_error(
    mocked_cmd,
    mocked_responses: responses,
    mocked_get_file_config: Mock,
    scenario: dict,
    expected_error_text: str,
):
    graph_name = generate_random_string()
    profile_name = generate_random_string()
    instance_name = "myinstance"
    resource_group_name = "myresourcegroup"

    # Build graph properties — use scenario override or default two-node config
    graph_properties = scenario.get("graph_properties") or {
        "nodes": [
            {
                "name": "source-node",
                "nodeType": "Source",
                "sourceSettings": {"endpointRef": "myendpoint1", "dataSources": ["test/topic"]},
            },
            {
                "name": "dest-node",
                "nodeType": "Destination",
                "destinationSettings": {"endpointRef": "myendpoint2", "dataDestination": "output/topic"},
            },
        ],
        "nodeConnections": [{"from": {"name": "source-node"}, "to": {"name": "dest-node"}}],
    }
    file_payload = {"properties": graph_properties}
    mocked_get_file_config.return_value = json.dumps(file_payload)

    source_endpoint = scenario.get("source_endpoint")
    if source_endpoint:
        source_status = scenario.get("source_endpoint_status", 200)
        mocked_responses.add(
            method=responses.GET,
            url=get_dataflow_endpoint_endpoint(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_endpoint_name=source_endpoint["name"],
            ),
            json=source_endpoint if source_status == 200 else {"error": {"code": "NotFound"}},
            status=source_status,
        )

    dest_endpoint = scenario.get("destination_endpoint")
    if dest_endpoint:
        mocked_responses.add(
            method=responses.GET,
            url=get_dataflow_endpoint_endpoint(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_endpoint_name=dest_endpoint["name"],
            ),
            json=dest_endpoint,
            status=200,
        )

    expected_error_type = scenario.get("expected_error_type", InvalidArgumentValueError)
    with pytest.raises(expected_error_type) as exc:
        apply_dataflow_graph(
            cmd=mocked_cmd,
            dataflow_graph_name=graph_name,
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            config_file="config.json",
            wait_sec=0.1,
        )

    assert expected_error_text in exc.value.args[0]


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("confirm_yes", [True, False, None])
def test_dataflow_graph_delete(mocked_cmd, mocked_responses: responses, confirm_yes, mocker):
    graph_name = generate_random_string()
    profile_name = generate_random_string()
    instance_name = generate_random_string()
    resource_group_name = generate_random_string()

    if not confirm_yes:
        mocker.patch(
            "azext_edge.edge.providers.orchestration.resources.dataflow_graphs.should_continue_prompt",
            return_value=False,
        )
    else:
        mocked_responses.add(
            method=responses.DELETE,
            url=get_dataflow_graph_endpoint(
                graph_name=graph_name,
                profile_name=profile_name,
                instance_name=instance_name,
                resource_group_name=resource_group_name,
            ),
            status=204,
        )

    delete_dataflow_graph(
        cmd=mocked_cmd,
        dataflow_graph_name=graph_name,
        profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
        confirm_yes=confirm_yes,
        wait_sec=0.1,
    )

    expected_calls = 0 if not confirm_yes else 1
    assert len(mocked_responses.calls) == expected_calls


# ---------------------------------------------------------------------------
# apply - graph node validation errors (artifact format + registryEndpointRef)
# ---------------------------------------------------------------------------

_GRAPH_NODE_BASE_PROPERTIES = {
    "nodes": [
        {
            "name": "src",
            "nodeType": "Source",
            "sourceSettings": {"endpointRef": "myendpoint1", "dataSources": ["t"]},
        },
        {
            "name": "dst",
            "nodeType": "Destination",
            "destinationSettings": {"endpointRef": "myendpoint2", "dataDestination": "t"},
        },
        {
            "name": "graph-node",
            "nodeType": "Graph",
            "graphSettings": {
                "registryEndpointRef": "myregistry",
                "artifact": "myartifact:1.0",
            },
        },
    ],
    "nodeConnections": [
        {"from": {"name": "src"}, "to": {"name": "graph-node"}},
        {"from": {"name": "graph-node"}, "to": {"name": "dst"}},
    ],
}


@pytest.mark.parametrize(
    "graph_settings_override, expected_error_text",
    [
        # Missing registryEndpointRef
        (
            {"artifact": "myartifact:1.0"},
            "is missing 'graphSettings.registryEndpointRef'",
        ),
        # Missing artifact
        (
            {"registryEndpointRef": "myregistry"},
            "is missing 'graphSettings.artifact'",
        ),
        # artifact with no colon
        (
            {"registryEndpointRef": "myregistry", "artifact": "myartifact"},
            "Expected format: '<artifact-name>:<version>'",
        ),
        # artifact colon at start
        (
            {"registryEndpointRef": "myregistry", "artifact": ":1.0"},
            "Expected format: '<artifact-name>:<version>'",
        ),
        # artifact colon at end
        (
            {"registryEndpointRef": "myregistry", "artifact": "myartifact:"},
            "Expected format: '<artifact-name>:<version>'",
        ),
    ],
)
def test_dataflow_graph_apply_graph_node_error(
    mocked_cmd,
    mocked_responses: responses,
    mocked_get_file_config,
    graph_settings_override: dict,
    expected_error_text: str,
):
    import copy

    graph_name = generate_random_string()
    profile_name = generate_random_string()
    instance_name = "myinstance"
    resource_group_name = "myresourcegroup"

    graph_properties = copy.deepcopy(_GRAPH_NODE_BASE_PROPERTIES)
    for node in graph_properties["nodes"]:
        if node["nodeType"] == "Graph":
            node["graphSettings"] = graph_settings_override

    file_payload = {"properties": graph_properties}
    mocked_get_file_config.return_value = json.dumps(file_payload)

    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_endpoint_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_endpoint_name="myendpoint1",
        ),
        json=get_mock_dataflow_endpoint_record(
            dataflow_endpoint_name="myendpoint1",
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            dataflow_endpoint_type="AIOLocalMqtt",
            host="aio-broker",
        ),
        status=200,
    )
    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_endpoint_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_endpoint_name="myendpoint2",
        ),
        json=get_mock_dataflow_endpoint_record(
            dataflow_endpoint_name="myendpoint2",
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            dataflow_endpoint_type="CustomMqtt",
        ),
        status=200,
    )

    # If registryEndpointRef is present, the code fetches it before validating artifact format
    if "registryEndpointRef" in graph_settings_override:
        mocked_responses.add(
            method=responses.GET,
            url=get_registry_endpoint_endpoint(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                registry_endpoint_name=graph_settings_override["registryEndpointRef"],
            ),
            json=get_mock_registry_endpoint_record(
                registry_endpoint_name=graph_settings_override["registryEndpointRef"],
                instance_name=instance_name,
                resource_group_name=resource_group_name,
            ),
            status=200,
        )

    with pytest.raises(InvalidArgumentValueError) as exc:
        apply_dataflow_graph(
            cmd=mocked_cmd,
            dataflow_graph_name=graph_name,
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            config_file="config.json",
            wait_sec=0.1,
        )

    assert expected_error_text in exc.value.args[0]


def test_dataflow_graph_apply_registry_endpoint_not_found(
    mocked_cmd,
    mocked_responses: responses,
    mocked_get_file_config,
):
    import copy

    graph_name = generate_random_string()
    profile_name = generate_random_string()
    instance_name = "myinstance"
    resource_group_name = "myresourcegroup"

    graph_properties = copy.deepcopy(_GRAPH_NODE_BASE_PROPERTIES)
    file_payload = {"properties": graph_properties}
    mocked_get_file_config.return_value = json.dumps(file_payload)

    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_endpoint_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_endpoint_name="myendpoint1",
        ),
        json=get_mock_dataflow_endpoint_record(
            dataflow_endpoint_name="myendpoint1",
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            dataflow_endpoint_type="AIOLocalMqtt",
            host="aio-broker",
        ),
        status=200,
    )
    mocked_responses.add(
        method=responses.GET,
        url=get_dataflow_endpoint_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_endpoint_name="myendpoint2",
        ),
        json=get_mock_dataflow_endpoint_record(
            dataflow_endpoint_name="myendpoint2",
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            dataflow_endpoint_type="CustomMqtt",
        ),
        status=200,
    )
    mocked_responses.add(
        method=responses.GET,
        url=get_registry_endpoint_endpoint(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            registry_endpoint_name="myregistry",
        ),
        json={"error": {"code": "ResourceNotFound", "message": "not found"}},
        status=404,
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        apply_dataflow_graph(
            cmd=mocked_cmd,
            dataflow_graph_name=graph_name,
            profile_name=profile_name,
            instance_name=instance_name,
            resource_group_name=resource_group_name,
            config_file="config.json",
            wait_sec=0.1,
        )

    assert "myregistry" in exc.value.args[0]
    assert "not found in instance 'myinstance'" in exc.value.args[0]
