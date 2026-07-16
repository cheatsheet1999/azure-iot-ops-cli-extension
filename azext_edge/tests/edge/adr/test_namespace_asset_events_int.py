# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from typing import List
import json
import pytest

from ...generators import generate_random_string
from ...helpers import run, wait_for_expected_count
from .namespace_helpers import (
    create_config_file,
    assert_point_properties,
    assert_event_properties,
    _save_json_to_file,
    _try_show_template,
)


pytestmark = [pytest.mark.rpsaas, pytest.mark.long_running]


def test_namespace_custom_asset_event_lifecycle_operations(
    asset_factory, tracked_files: List[str]
):
    """Test complete lifecycle of custom asset event-group and datapoint operations."""
    # Setup from shared fixtures
    info = asset_factory("custom")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    event_group_name = f"event-group-{generate_random_string(6, force_lower=True)}"
    datapoint_name_1 = f"dp1-{generate_random_string(6, force_lower=True)}"
    datapoint_name_2 = f"dp2-{generate_random_string(6, force_lower=True)}"

    # 1. CREATE EVENT GROUP
    custom_config_path, custom_config = create_config_file(tracked_files)
    event_destinations = "topic=factory/custom/events qos=Qos1 retain=Never ttl=3600"

    event_result = run(
        f"az iot ops ns asset custom event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} "
        f"--config {custom_config_path} --destination {event_destinations}"
    )

    assert_event_properties(
        event_result,
        name=event_group_name,
        custom_configuration=custom_config,
    )

    # 2. LIST EVENT GROUPS
    event_groups_list = run(
        f"az iot ops ns asset custom event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    assert len(event_groups_list) >= 1
    event_group_names = [eg["name"] for eg in event_groups_list]
    assert event_group_name in event_group_names

    # 3. SHOW EVENT GROUP
    event_show = run(
        f"az iot ops ns asset custom event-group show --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    assert_event_properties(
        event_show,
        name=event_group_name,
    )

    # 4. UPDATE EVENT GROUP
    updated_data_source = "temperature.alarm.critical"
    custom_config_path, custom_config = create_config_file(tracked_files)

    updated_event = run(
        f"az iot ops ns asset custom event-group update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source {updated_data_source} "
        f"--config {custom_config_path}"
    )

    assert_event_properties(
        updated_event,
        name=event_group_name,
        data_source=updated_data_source,
        custom_configuration=custom_config,
    )

    # 5. CREATE EVENT WITH REPLACE
    replaced_data_source = "temperature.alarm.replaced"
    replaced_event = run(
        f"az iot ops ns asset custom event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source {replaced_data_source} "
        f"--replace"
    )

    assert_event_properties(
        replaced_event,
        name=event_group_name,
        data_source=replaced_data_source,
    )

    # 6. ADD EVENT DATAPOINT
    custom_config_path, custom_config = create_config_file(tracked_files)

    datapoint_result = run(
        f"az iot ops ns asset custom event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_1} "
        f"--config {custom_config_path}"
    )

    assert_point_properties(
        datapoint_result,
        name=datapoint_name_1,
        custom_configuration=custom_config
    )

    # 7. ADD ANOTHER EVENT DATAPOINT
    datapoint_data_source_2 = "temperature.level"
    custom_config_path, custom_config = create_config_file(tracked_files)

    datapoint_result_2 = run(
        f"az iot ops ns asset custom event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_2} "
        f"--data-source {datapoint_data_source_2} --config {custom_config_path}"
    )

    assert_point_properties(
        datapoint_result_2,
        name=datapoint_name_2,
        data_source=datapoint_data_source_2,
        custom_configuration=custom_config
    )

    # 8. LIST EVENT DATAPOINTS
    datapoints_list = wait_for_expected_count(
        list_cmd=(
            f"az iot ops ns asset custom event list --asset {asset_name} --instance {instance_name} "
            f"-g {resource_group} --event-group {event_group_name}"
        ),
        expected_count=2,
        expected_names=[datapoint_name_1, datapoint_name_2],
    )

    assert len(datapoints_list) >= 2

    # 9. REPLACE EVENT DATAPOINT
    replaced_datapoint_source = "temperature.severity.replaced"
    replaced_datapoint = run(
        f"az iot ops ns asset custom event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_1} "
        f"--data-source {replaced_datapoint_source} --replace"
    )

    assert_point_properties(
        replaced_datapoint,
        name=datapoint_name_1,
        data_source=replaced_datapoint_source
    )

    # 10. REMOVE EVENT DATAPOINT
    run(
        f"az iot ops ns asset custom event remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_1}"
    )

    # Verify removal by listing
    remaining_datapoints = run(
        f"az iot ops ns asset custom event list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name}"
    )

    remaining_names = [dp["name"] for dp in remaining_datapoints]
    assert datapoint_name_1 not in remaining_names
    assert datapoint_name_2 in remaining_names

    # 11. REMOVE EVENT
    run(
        f"az iot ops ns asset custom event-group remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    # Verify removal by listing
    remaining_event_groups = run(
        f"az iot ops ns asset custom event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    remaining_event_group_names = [eg["name"] for eg in remaining_event_groups]
    assert event_group_name not in remaining_event_group_names


def test_namespace_opcua_asset_event_lifecycle_operations(asset_factory):
    """Test complete lifecycle of OPC UA asset event-group operations (events only)."""
    # Setup from shared fixtures
    info = asset_factory("opcua")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    event_group_name = f"event-group-{generate_random_string(6, force_lower=True)}"

    # 1. CREATE EVENT WITH FULL OPCUA CONFIGURATION
    event_destinations = "topic=factory/opcua/events qos=Qos0 retain=Keep ttl=7200"
    publishing_interval = 500
    queue_size = 10
    start_instance = "ns=3;i=3001"
    condition_refresh_interval = 30000  # milliseconds

    event_result = run(
        f"az iot ops ns asset opcua event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} "
        f"--destination {event_destinations} --publish-int {publishing_interval} "
        f"--queue-size {queue_size} --start-inst \"{start_instance}\" "
        f"--condition-refresh-int {condition_refresh_interval}"
    )

    assert_event_properties(
        event_result,
        name=event_group_name,
        opcua_configuration={"startInstance": start_instance, "conditionRefreshInterval": condition_refresh_interval},
    )

    # 2. LIST EVENT GROUPS
    event_groups_list = run(
        f"az iot ops ns asset opcua event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    assert len(event_groups_list) >= 1
    event_group_names = [eg["name"] for eg in event_groups_list]
    assert event_group_name in event_group_names

    # 3. SHOW EVENT GROUP
    event_show = run(
        f"az iot ops ns asset opcua event-group show --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    assert_event_properties(
        event_show,
        name=event_group_name,
    )

    # 4. UPDATE EVENT GROUP
    updated_data_source = "ns=3;i=1000"
    updated_publishing_interval = 1000
    updated_queue_size = 15
    updated_condition_refresh_interval = 60000  # milliseconds

    updated_event = run(
        f"az iot ops ns asset opcua event-group update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source \"{updated_data_source}\" "
        f"--publish-int {updated_publishing_interval} --queue-size {updated_queue_size} "
        f"--condition-refresh-int {updated_condition_refresh_interval}"
    )

    assert_event_properties(
        updated_event,
        name=event_group_name,
        data_source=updated_data_source,
        opcua_configuration={"conditionRefreshInterval": updated_condition_refresh_interval},
    )

    # 5. CREATE EVENT GROUP WITH REPLACE
    replaced_data_source = "ns=4;i=1000"
    replaced_event = run(
        f"az iot ops ns asset opcua event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source \"{replaced_data_source}\" "
        f"--replace"
    )

    assert_event_properties(
        replaced_event,
        name=event_group_name,
        data_source=replaced_data_source
    )

    # 6. ADD INDIVIDUAL EVENT WITH CONDITION REFRESH
    event_name = f"event-{generate_random_string(6, force_lower=True)}"
    event_result = run(
        f"az iot ops ns asset opcua event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {event_name} "
        "--condition-refresh"
    )
    assert isinstance(event_result, list)
    created_event = next((ev for ev in event_result if ev["name"] == event_name), None)
    assert created_event is not None
    assert json.loads(created_event["eventConfiguration"])["conditionRefresh"] is True

    # 7. REMOVE INDIVIDUAL EVENT
    run(
        f"az iot ops ns asset opcua event remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {event_name}"
    )
    remaining_events = run(
        f"az iot ops ns asset opcua event list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name}"
    )
    assert not any(ev["name"] == event_name for ev in remaining_events)

    # 8. REMOVE EVENT GROUP
    run(
        f"az iot ops ns asset opcua event-group remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    # Verify removal by listing
    remaining_event_groups = run(
        f"az iot ops ns asset opcua event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    remaining_event_group_names = [eg["name"] for eg in remaining_event_groups]
    assert event_group_name not in remaining_event_group_names


def test_namespace_onvif_asset_event_lifecycle_operations(asset_factory):
    """Test complete lifecycle of ONVIF asset event-group operations (events only)."""
    # Setup from shared fixtures
    info = asset_factory("onvif")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    event_group_name = f"event-group-{generate_random_string(6, force_lower=True)}"

    # 1. CREATE EVENT GROUP
    event_destinations = "topic=factory/onvif/events qos=Qos1 retain=Never ttl=1800"

    event_result = run(
        f"az iot ops ns asset onvif event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} "
        f"--destination {event_destinations}"
    )

    assert_event_properties(
        event_result,
        name=event_group_name,
    )

    # 2. LIST EVENT GROUPS
    event_groups_list = run(
        f"az iot ops ns asset onvif event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    assert len(event_groups_list) >= 1
    event_group_names = [ev["name"] for ev in event_groups_list]
    assert event_group_name in event_group_names

    # 3. SHOW EVENT GROUP
    event_show = run(
        f"az iot ops ns asset onvif event-group show --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    assert_event_properties(
        event_show,
        name=event_group_name,
    )

    # 4. UPDATE EVENT GROUP
    updated_data_source = "motion.detection.enhanced"
    updated_event_destinations = "topic=factory/onvif/events/enhanced qos=Qos0 retain=Keep ttl=3600"

    updated_event = run(
        f"az iot ops ns asset onvif event-group update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source {updated_data_source} "
        f"--destination {updated_event_destinations}"
    )

    assert_event_properties(
        updated_event,
        name=event_group_name,
        data_source=updated_data_source,
    )

    # 5. CREATE EVENT WITH REPLACE
    replaced_data_source = "motion.detection.replaced"
    replaced_event = run(
        f"az iot ops ns asset onvif event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source {replaced_data_source} "
        f"--replace"
    )

    assert_event_properties(
        replaced_event,
        name=event_group_name,
        data_source=replaced_data_source
    )

    # 5b. ADD EVENT to the event group
    event_name = f"event-{generate_random_string(6, force_lower=True)}"
    event_result = run(
        f"az iot ops ns asset onvif event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {event_name}"
    )
    assert isinstance(event_result, list)
    assert any(ev["name"] == event_name for ev in event_result)

    # 5c. LIST EVENTS
    events_list = run(
        f"az iot ops ns asset onvif event list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name}"
    )
    assert any(ev["name"] == event_name for ev in events_list)

    # 5d. REMOVE EVENT
    run(
        f"az iot ops ns asset onvif event remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {event_name}"
    )
    remaining_events = run(
        f"az iot ops ns asset onvif event list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name}"
    )
    assert not any(ev["name"] == event_name for ev in remaining_events)

    # 6. REMOVE EVENT GROUP
    run(
        f"az iot ops ns asset onvif event-group remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    # Verify removal by listing
    remaining_event_groups = run(
        f"az iot ops ns asset onvif event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    remaining_event_group_names = [ev["name"] for ev in remaining_event_groups]
    assert event_group_name not in remaining_event_group_names


def test_namespace_sse_asset_event_lifecycle_operations(asset_factory):
    """Test complete lifecycle of SSE asset event-group operations (events only)."""
    # Setup from shared fixtures
    info = asset_factory("sse")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    event_group_name = f"event-group-{generate_random_string(6, force_lower=True)}"

    # 1. CREATE EVENT GROUP
    event_destinations = "topic=factory/sse/events qos=Qos1 retain=Never ttl=1800"

    event_result = run(
        f"az iot ops ns asset sse event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} "
        f"--destination {event_destinations}"
    )

    assert_event_properties(
        event_result,
        name=event_group_name,
    )

    # 2. LIST EVENT GROUPS
    event_groups_list = run(
        f"az iot ops ns asset sse event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    assert len(event_groups_list) >= 1
    event_group_names = [ev["name"] for ev in event_groups_list]
    assert event_group_name in event_group_names

    # 3. SHOW EVENT GROUP
    event_show = run(
        f"az iot ops ns asset sse event-group show --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    assert_event_properties(
        event_show,
        name=event_group_name,
    )

    # 4. UPDATE EVENT GROUP
    updated_data_source = "/events/alerts/critical"
    updated_event_destinations = "topic=factory/sse/events/critical qos=Qos0 retain=Keep ttl=3600"

    updated_event = run(
        f"az iot ops ns asset sse event-group update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source {updated_data_source} "
        f"--destination {updated_event_destinations}"
    )

    assert_event_properties(
        updated_event,
        name=event_group_name,
        data_source=updated_data_source,
    )

    # 5. CREATE EVENT WITH REPLACE
    replaced_data_source = "/events/alerts/replaced"
    replaced_event = run(
        f"az iot ops ns asset sse event-group add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name} --data-source {replaced_data_source} "
        f"--replace"
    )

    assert_event_properties(
        replaced_event,
        name=event_group_name,
        data_source=replaced_data_source
    )

    # 6. ADD INDIVIDUAL EVENTS TO EVENT GROUP
    datapoint_name_1 = f"event-{generate_random_string(6, force_lower=True)}"
    datapoint_name_2 = f"event-{generate_random_string(6, force_lower=True)}"
    datapoint_data_source = "/events/temperature/severity"
    event_destinations = "topic=factory/sse/temperature/severity qos=Qos1 retain=Keep ttl=1800"

    # Add first individual event (SSE uses event destinations, not sampling intervals)
    datapoint_result = run(
        f"az iot ops ns asset sse event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_1} "
        f"--destination {event_destinations}"
    )

    assert_point_properties(
        datapoint_result,
        name=datapoint_name_1,
    )

    # 7. ADD SECOND INDIVIDUAL EVENT
    datapoint_2_data_source = "/events/pressure/alert"
    datapoint_2_destinations = "topic=factory/sse/pressure/alert qos=Qos0 retain=Never ttl=900"

    datapoint_2_result = run(
        f"az iot ops ns asset sse event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_2} "
        f"--data-source {datapoint_2_data_source} --destination {datapoint_2_destinations}"
    )

    assert_point_properties(
        datapoint_2_result,
        name=datapoint_name_2,
        data_source=datapoint_2_data_source,
    )

    # 8. LIST INDIVIDUAL EVENTS IN EVENT GROUP
    events_list = run(
        f"az iot ops ns asset sse event list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name}"
    )

    event_names = [ev["name"] for ev in events_list]
    assert datapoint_name_1 in event_names
    assert datapoint_name_2 in event_names
    assert len(events_list) >= 2

    # 9. UPDATE INDIVIDUAL EVENT WITH REPLACE
    updated_datapoint_destinations = "topic=factory/sse/temperature/updated qos=Qos0 retain=Never ttl=600"

    updated_datapoint = run(
        f"az iot ops ns asset sse event add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_1} "
        f"--data-source {datapoint_data_source} --destination {updated_datapoint_destinations} "
        f"--replace"
    )

    assert_point_properties(
        updated_datapoint,
        name=datapoint_name_1,
        data_source=datapoint_data_source,
    )

    # 10. REMOVE INDIVIDUAL EVENT
    run(
        f"az iot ops ns asset sse event remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name} --name {datapoint_name_1}"
    )

    # Verify individual event removal
    remaining_events_after_remove = run(
        f"az iot ops ns asset sse event list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --event-group {event_group_name}"
    )

    remaining_event_names = [ev["name"] for ev in remaining_events_after_remove]
    assert datapoint_name_1 not in remaining_event_names
    assert datapoint_name_2 in remaining_event_names

    # 11. REMOVE EVENT GROUP
    run(
        f"az iot ops ns asset sse event-group remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {event_group_name}"
    )

    # Verify removal by listing
    remaining_event_groups = run(
        f"az iot ops ns asset sse event-group list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    remaining_event_group_names = [ev["name"] for ev in remaining_event_groups]
    assert event_group_name not in remaining_event_group_names


# ---------------------------------------------------------------------------
# Generalized event-group / event commands — OPC UA (bundled metadata)
# ---------------------------------------------------------------------------


def test_generalized_event_lifecycle_opcua(asset_factory, tracked_files: List[str]):
    """Full lifecycle of generalized event-group + event commands on an OPC UA asset.

    Flow:
      1. --show-template config  ->  discover schema
      2. Fill connector-specific values in the returned template
      3. Use filled template as --event-group-config / --event-config
      4. CRUD: add / show / list / update / remove
      5. Export round-trip
    """
    info = asset_factory("opcua")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    eg_name = f"gen-eg-{generate_random_string(6, force_lower=True)}"
    eg_name_2 = f"gen-eg2-{generate_random_string(6, force_lower=True)}"
    event_name = f"gen-ev-{generate_random_string(6, force_lower=True)}"
    data_source = "ns=2;s=Boiler"
    ev_data_source = "ns=2;s=Boiler.Event"

    # 1. SHOW-TEMPLATE - event-group
    eg_template = run(
        f"az iot ops ns asset event-group add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {eg_name} --show-template config"
    )
    assert isinstance(eg_template, dict)
    assert "connectorType" in eg_template
    assert "eventGroupConfig" in eg_template

    eg_config = eg_template.copy()
    eg_config["eventGroupConfig"]["eventGroupConfiguration"] = {
        "publishingInterval": 1000,
        "queueSize": 5,
    }
    eg_config["eventGroupConfig"].pop("destinations", None)
    eg_config_file = _save_json_to_file(eg_config, tracked_files)

    # 2. ADD event-group with config
    added_eg = run(
        f"az iot ops ns asset event-group add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {eg_name} --data-source '{data_source}' "
        f"--event-group-config {eg_config_file}"
    )
    assert_event_properties(
        added_eg, name=eg_name, data_source=data_source,
        opcua_configuration={"publishingInterval": 1000},
    )

    # 3. SHOW event-group
    shown_eg = run(
        f"az iot ops ns asset event-group show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {eg_name}"
    )
    assert_event_properties(shown_eg, name=eg_name, data_source=data_source)

    # 4. LIST event-groups
    eg_list = run(
        f"az iot ops ns asset event-group list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )
    assert any(g["name"] == eg_name for g in eg_list)

    # 5. ADD a second event-group (minimal)
    added_eg_2 = run(
        f"az iot ops ns asset event-group add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {eg_name_2} --data-source '{data_source}'"
    )
    assert_event_properties(added_eg_2, name=eg_name_2)
    eg_names = [g["name"] for g in run(
        f"az iot ops ns asset event-group list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )]
    assert eg_name in eg_names and eg_name_2 in eg_names

    # 6. UPDATE event-group
    updated_source = "ns=2;s=Boiler.Updated"
    eg_config["eventGroupConfig"]["eventGroupConfiguration"]["publishingInterval"] = 2000
    updated_eg_file = _save_json_to_file(eg_config, tracked_files)
    updated_eg = run(
        f"az iot ops ns asset event-group update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {eg_name} --data-source '{updated_source}' "
        f"--event-group-config {updated_eg_file}"
    )
    assert_event_properties(
        updated_eg, name=eg_name, data_source=updated_source,
        opcua_configuration={"publishingInterval": 2000},
    )

    # 7. SHOW-TEMPLATE - event
    event_template = run(
        f"az iot ops ns asset event add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--event-group {eg_name} --name {event_name} "
        f"--data-source '{ev_data_source}' --show-template config"
    )
    assert isinstance(event_template, dict)
    assert "connectorType" in event_template
    assert "eventConfig" in event_template

    event_config = event_template.copy()
    event_config["eventConfig"]["eventConfiguration"] = {
        "queueSize": 3,
    }
    event_config["eventConfig"].pop("destinations", None)
    event_config_file = _save_json_to_file(event_config, tracked_files)

    # 8. ADD event with config
    added_events = run(
        f"az iot ops ns asset event add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--event-group {eg_name} --name {event_name} "
        f"--data-source '{ev_data_source}' --event-config {event_config_file}"
    )
    assert_point_properties(added_events, name=event_name, data_source=ev_data_source)

    # 9. LIST events
    ev_list = run(
        f"az iot ops ns asset event list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --event-group {eg_name}"
    )
    assert any(ev["name"] == event_name for ev in ev_list)

    # 10. REPLACE event
    replaced_ev_source = "ns=2;s=Boiler.Replaced"
    replaced_events = run(
        f"az iot ops ns asset event add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--event-group {eg_name} --name {event_name} "
        f"--data-source '{replaced_ev_source}' --replace"
    )
    assert_point_properties(replaced_events, name=event_name, data_source=replaced_ev_source)

    # 11. EXPORT event-groups
    export_result = run(
        f"az iot ops ns asset event-group export --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --output-dir /tmp --replace"
    )
    assert export_result["event_group_count"] >= 1
    tracked_files.append(export_result["file_path"])

    # 12. EXPORT events
    ev_export_result = run(
        f"az iot ops ns asset event export --asset {asset_name} "
        f"--event-group {eg_name} --instance {instance_name} -g {resource_group} "
        f"--output-dir /tmp --replace"
    )
    assert ev_export_result["event_count"] >= 1
    tracked_files.append(ev_export_result["file_path"])

    # 13. REMOVE event
    run(
        f"az iot ops ns asset event remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--event-group {eg_name} --name {event_name}"
    )
    ev_list_after = run(
        f"az iot ops ns asset event list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --event-group {eg_name}"
    )
    assert not any(ev["name"] == event_name for ev in (ev_list_after or []))

    # 14. REMOVE event-groups
    for eg in [eg_name, eg_name_2]:
        run(
            f"az iot ops ns asset event-group remove --asset {asset_name} "
            f"--instance {instance_name} -g {resource_group} --name {eg}"
        )
    remaining = [g["name"] for g in (run(
        f"az iot ops ns asset event-group list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    ) or [])]
    assert eg_name not in remaining and eg_name_2 not in remaining


# ---------------------------------------------------------------------------
# Generalized event-group / event commands — custom (connector template required)
# ---------------------------------------------------------------------------


def test_generalized_event_lifecycle_custom(asset_factory, tracked_files: List[str]):
    """Generalized event-group + event lifecycle on a custom asset.

    A connector template must exist in the instance for --show-template / --event-group-config
    to resolve connector metadata. When no template is installed, --show-template returns an
    empty dict and the test exercises the metadata-free path (no config payload).
    """
    info = asset_factory("custom")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    eg_name = f"gen-eg-{generate_random_string(6, force_lower=True)}"
    event_name = f"gen-ev-{generate_random_string(6, force_lower=True)}"
    data_source = "custom/boiler"
    ev_data_source = "custom/boiler/event"

    # 1. SHOW-TEMPLATE - event-group (may be empty when no connector template installed)
    eg_template = _try_show_template(
        f"az iot ops ns asset event-group add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {eg_name} --show-template config"
    )

    eg_config_arg = ""
    if eg_template:
        assert "connectorType" in eg_template
        assert "eventGroupConfig" in eg_template
        eg_config = eg_template.copy()
        eg_config["eventGroupConfig"].pop("destinations", None)
        eg_config_file = _save_json_to_file(eg_config, tracked_files)
        eg_config_arg = f"--event-group-config {eg_config_file}"

    # 2. ADD event-group
    added_eg = run(
        f"az iot ops ns asset event-group add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {eg_name} --data-source '{data_source}' {eg_config_arg}"
    )
    assert_event_properties(added_eg, name=eg_name, data_source=data_source)

    # 3. LIST event-groups
    eg_list = run(
        f"az iot ops ns asset event-group list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )
    assert any(g["name"] == eg_name for g in eg_list)

    # 4. SHOW-TEMPLATE - event (may be empty)
    event_template = _try_show_template(
        f"az iot ops ns asset event add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--event-group {eg_name} --name {event_name} "
        f"--data-source '{ev_data_source}' --show-template config"
    )

    event_config_arg = ""
    if event_template:
        assert "connectorType" in event_template
        assert "eventConfig" in event_template
        event_config = event_template.copy()
        event_config["eventConfig"].pop("destinations", None)
        event_config_file = _save_json_to_file(event_config, tracked_files)
        event_config_arg = f"--event-config {event_config_file}"

    # 5. ADD event
    added_events = run(
        f"az iot ops ns asset event add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--event-group {eg_name} --name {event_name} "
        f"--data-source '{ev_data_source}' {event_config_arg}"
    )
    assert_point_properties(added_events, name=event_name, data_source=ev_data_source)

    # 6. LIST events
    ev_list = run(
        f"az iot ops ns asset event list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --event-group {eg_name}"
    )
    assert any(ev["name"] == event_name for ev in ev_list)

    # 7. REMOVE event
    run(
        f"az iot ops ns asset event remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--event-group {eg_name} --name {event_name}"
    )
    ev_list_after = run(
        f"az iot ops ns asset event list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --event-group {eg_name}"
    )
    assert not any(ev["name"] == event_name for ev in (ev_list_after or []))

    # 8. REMOVE event-group
    run(
        f"az iot ops ns asset event-group remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {eg_name}"
    )
    remaining = [g["name"] for g in (run(
        f"az iot ops ns asset event-group list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    ) or [])]
    assert eg_name not in remaining
