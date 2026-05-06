# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import json
import os
import tempfile

import pytest

from ....generators import generate_random_string
from ....helpers import run

# pytest mark for rpsaas (cloud-side) tests
pytestmark = pytest.mark.rpsaas


@pytest.fixture(scope="function")
def dataflow_graph_test_setup(settings):
    from ....settings import EnvironmentVariables

    settings.add_to_config(EnvironmentVariables.rg.value)
    settings.add_to_config(EnvironmentVariables.instance.value)
    if not all([settings.env.azext_edge_instance, settings.env.azext_edge_rg]):
        raise AssertionError(
            "Cannot run dataflow graph tests without an instance and resource group. "
            f"Current settings:\n {settings}"
        )

    yield {
        "resourceGroup": settings.env.azext_edge_rg,
        "instanceName": settings.env.azext_edge_instance,
    }


def _write_graph_config(nodes: list, node_connections: list) -> str:
    """Write a graph config JSON to a temp file and return its path."""
    config = {"nodes": nodes, "nodeConnections": node_connections}
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f)
    except Exception:
        os.close(fd)
        raise
    return path


def _default_graph_config(source_endpoint_ref: str, dest_endpoint_ref: str) -> tuple:
    """Return (nodes, node_connections) for a minimal valid graph."""
    nodes = [
        {
            "name": "source-node",
            "nodeType": "Source",
            "sourceSettings": {
                "endpointRef": source_endpoint_ref,
                "dataSources": ["test/topic"],
            },
        },
        {
            "name": "dest-node",
            "nodeType": "Destination",
            "destinationSettings": {
                "endpointRef": dest_endpoint_ref,
                "dataDestination": "output/topic",
            },
        },
    ]
    node_connections = [
        {"from": {"name": "source-node"}, "to": {"name": "dest-node"}}
    ]
    return nodes, node_connections


def test_dataflow_graph(dataflow_graph_test_setup, tracked_resources, tracked_files):
    rg = dataflow_graph_test_setup["resourceGroup"]
    instance = dataflow_graph_test_setup["instanceName"]
    profile_name = "default"

    # Discover an MQTT-family endpoint to use for source and destination.
    # DataFlowGraphs validation accepts all MQTT-family endpoint types
    # (Mqtt, AIOLocalMqtt, EventGrid, CustomMqtt).
    endpoints = run(f"az iot ops dataflow endpoint list -g {rg} -i {instance}")
    mqtt_endpoints = [
        ep for ep in endpoints
        if ep.get("properties", {}).get("endpointType") in ("Mqtt", "AIOLocalMqtt", "EventGrid", "CustomMqtt")
    ]
    if not mqtt_endpoints:
        pytest.skip(
            "No MQTT-family endpoint (Mqtt, AIOLocalMqtt, EventGrid, CustomMqtt) found in instance — "
            "skipping dataflow graph integration test. "
            "Create at least one MQTT endpoint before running this test."
        )

    source_ep = mqtt_endpoints[0]["name"]
    dest_ep = mqtt_endpoints[-1]["name"]  # may be the same as source; that's fine

    graph_name = f"test-graph-{generate_random_string(force_lower=True, size=6)}"
    nodes, connections = _default_graph_config(
        source_endpoint_ref=source_ep,
        dest_endpoint_ref=dest_ep,
    )
    config_path = _write_graph_config(nodes=nodes, node_connections=connections)
    tracked_files.append(config_path)

    # APPLY (create)
    graph = run(
        f"az iot ops dataflowgraph apply -n {graph_name} -g {rg} -i {instance} "
        f"--profile {profile_name} --config-file {config_path}"
    )
    tracked_resources.append(graph["id"])
    assert_dataflow_graph(graph=graph, name=graph_name, resource_group=rg)

    # SHOW
    show_result = run(
        f"az iot ops dataflowgraph show -n {graph_name} -g {rg} -i {instance} --profile {profile_name}"
    )
    assert_dataflow_graph(graph=show_result, name=graph_name, resource_group=rg)

    # LIST
    list_result = run(
        f"az iot ops dataflowgraph list -g {rg} -i {instance} --profile {profile_name}"
    )
    list_names = [g["name"] for g in list_result]
    assert graph_name in list_names

    # APPLY again (update — add a Graph node if a registry endpoint is available)
    registry_endpoints = run(f"az iot ops registry list -g {rg} -i {instance}")
    if registry_endpoints:
        registry_ep = registry_endpoints[0]["name"]
        updated_nodes = nodes + [
            {
                "name": "graph-node",
                "nodeType": "Graph",
                "graphSettings": {
                    "registryEndpointRef": registry_ep,
                    "artifact": "my-module:1.0.0",
                },
            }
        ]
        updated_connections = connections + [
            {"from": {"name": "source-node"}, "to": {"name": "graph-node"}},
            {"from": {"name": "graph-node"}, "to": {"name": "dest-node"}},
        ]
        updated_config_path = _write_graph_config(nodes=updated_nodes, node_connections=updated_connections)
        tracked_files.append(updated_config_path)

        updated_graph = run(
            f"az iot ops dataflowgraph apply -n {graph_name} -g {rg} -i {instance} "
            f"--profile {profile_name} --config-file {updated_config_path}"
        )
        assert_dataflow_graph(graph=updated_graph, name=graph_name, resource_group=rg)
        node_names = [n["name"] for n in updated_graph.get("properties", {}).get("nodes", [])]
        assert "graph-node" in node_names

    # DELETE
    run(f"az iot ops dataflowgraph delete -n {graph_name} -g {rg} -i {instance} --profile {profile_name} -y")
    tracked_resources.remove(graph["id"])

    # Confirm deletion — should no longer appear in list
    list_after = run(
        f"az iot ops dataflowgraph list -g {rg} -i {instance} --profile {profile_name}"
    )
    assert graph_name not in [g["name"] for g in list_after]


def assert_dataflow_graph(graph: dict, **expected):
    assert graph["name"] == expected["name"]
    assert graph["resourceGroup"] == expected["resource_group"]
    props = graph.get("properties", {})
    assert props.get("provisioningState") == "Succeeded"
    assert isinstance(props.get("nodes"), list)
    assert len(props["nodes"]) >= 1
