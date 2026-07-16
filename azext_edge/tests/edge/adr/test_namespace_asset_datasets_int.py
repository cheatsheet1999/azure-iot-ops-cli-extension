# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import pytest
from typing import List

from ...generators import generate_random_string
from ...helpers import run, wait_for_expected_count
from .namespace_helpers import (
    create_config_file,
    assert_point_properties,
    assert_dataset_properties,
    _save_json_to_file,
    _try_show_template,
)


pytestmark = [pytest.mark.rpsaas, pytest.mark.long_running]


def test_namespace_custom_asset_dataset_lifecycle_operations(
    asset_factory, tracked_files: List[str]
):
    """Test complete lifecycle of custom asset dataset and datapoint operations."""
    # Setup from shared fixtures
    info = asset_factory("custom")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    dataset_name_1 = f"dataset{generate_random_string(6, force_lower=True)}"
    dataset_name_2 = f"dataset2{generate_random_string(6, force_lower=True)}"
    datapoint_name_1 = f"dp1-{generate_random_string(6, force_lower=True)}"
    datapoint_name_2 = f"dp2-{generate_random_string(6, force_lower=True)}"

    # 1. CREATE DATASET
    dataset_destinations = "topic=factory/temperature qos=Qos1 retain=Keep ttl=3600"
    custom_config_path, custom_config = create_config_file(tracked_files)

    # Add custom asset dataset
    dataset_result = run(
        f"az iot ops ns asset custom dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {dataset_destinations} "
        f"--config {custom_config_path}"
    )

    assert_dataset_properties(
        dataset_result,
        name=dataset_name_1,
        asset_type="custom",
        custom_configuration=custom_config
    )

    # 2. LIST DATASETS
    datasets_list = run(
        f"az iot ops ns asset custom dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    dataset_names = [dataset["name"] for dataset in datasets_list]
    assert dataset_name_1 in dataset_names
    assert len(datasets_list) >= 1

    # 3. SHOW DATASET
    shown_dataset = run(
        f"az iot ops ns asset custom dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    assert_dataset_properties(
        shown_dataset,
        name=dataset_name_1,
        asset_type="custom"
    )

    # 4. UPDATE DATASET
    updated_data_source = "sensor/temperature_updated"
    updated_destinations = "topic=factory/temperature_v2 qos=Qos0 retain=Never ttl=1800"
    custom_config_path, custom_config = create_config_file(tracked_files)

    updated_dataset = run(
        f"az iot ops ns asset custom dataset update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source {updated_data_source} "
        f"--destination {updated_destinations} "
        f"--config {custom_config_path}"
    )

    assert_dataset_properties(
        updated_dataset,
        name=dataset_name_1,
        data_source=updated_data_source,
        asset_type="custom",
        custom_configuration=custom_config
    )

    # 5a. TEST DATASET REPLACE FUNCTIONALITY
    # Replace dataset with --replace flag
    replaced_data_source = "sensor/temperature_replaced"
    custom_config_path, custom_config = create_config_file(tracked_files)

    replaced_dataset = run(
        f"az iot ops ns asset custom dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source {replaced_data_source} "
        f"--config {custom_config_path} --replace"
    )

    assert_dataset_properties(
        replaced_dataset,
        name=dataset_name_1,
        data_source=replaced_data_source,
        asset_type="custom",
        custom_configuration=custom_config
    )

    # 5b. TEST MULTIPLE DATASETS
    data_source = "sensor/temperature_replaced"

    dataset = run(
        f"az iot ops ns asset custom dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_2} "
        f"--data-source '{data_source}' "
        f"--config {custom_config_path} --replace"
    )

    assert_dataset_properties(
        dataset,
        name=dataset_name_2,
        data_source=data_source,
        asset_type="custom",
    )

    # 6. ADD DATASET DATAPOINTS
    # Add first datapoint
    datapoint_data_source_1 = "sensor/temperature/value"
    custom_config_path, custom_config = create_config_file(tracked_files)

    datapoint_result_1 = run(
        f"az iot ops ns asset custom datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_1} --data-source {datapoint_data_source_1} "
        f"--config {custom_config_path}"
    )

    assert_point_properties(
        datapoint_result_1,
        name=datapoint_name_1,
        data_source=datapoint_data_source_1
    )

    # Add second datapoint
    datapoint_data_source_2 = "sensor/humidity/value"
    custom_config_path, custom_config = create_config_file(tracked_files)

    datapoint_result_2 = run(
        f"az iot ops ns asset custom datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_2} --data-source {datapoint_data_source_2} "
        f"--config {custom_config_path}"
    )

    assert_point_properties(
        datapoint_result_2,
        name=datapoint_name_2,
        data_source=datapoint_data_source_2
    )

    # 7. LIST DATASET DATAPOINTS
    datapoints_list = wait_for_expected_count(
        list_cmd=(
            f"az iot ops ns asset custom datapoint list --asset {asset_name} "
            f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1}"
        ),
        expected_count=2,
        expected_names=[datapoint_name_1, datapoint_name_2],
        reissue_cmds={
            datapoint_name_1: (
                f"az iot ops ns asset custom datapoint add --asset {asset_name} "
                f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
                f"--name {datapoint_name_1} --data-source {datapoint_data_source_1}"
            ),
            datapoint_name_2: (
                f"az iot ops ns asset custom datapoint add --asset {asset_name} "
                f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
                f"--name {datapoint_name_2} --data-source {datapoint_data_source_2}"
            ),
        },
    )

    assert len(datapoints_list) >= 2

    # 8. TEST DATAPOINT REPLACE FUNCTIONALITY
    # Replace first datapoint with --replace flag
    replaced_datapoint_data_source = "sensor/temperature/replaced_value"
    custom_config_path, custom_config = create_config_file(tracked_files)

    replaced_datapoint = run(
        f"az iot ops ns asset custom datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_1} --data-source {replaced_datapoint_data_source} "
        f"--config {custom_config_path} --replace"
    )

    assert_point_properties(
        replaced_datapoint,
        name=datapoint_name_1,
        data_source=replaced_datapoint_data_source
    )

    # 9. REMOVE DATASET DATAPOINT
    run(
        f"az iot ops ns asset custom datapoint remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_2}"
    )

    # Verify datapoint removal
    datapoints_list_after_remove = run(
        f"az iot ops ns asset custom datapoint list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1}"
    )

    remaining_datapoint_names = [dp["name"] for dp in datapoints_list_after_remove]
    assert datapoint_name_1 in remaining_datapoint_names
    assert datapoint_name_2 not in remaining_datapoint_names

    # 10. REMOVE DATASET
    run(
        f"az iot ops ns asset custom dataset remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    # Verify dataset removal
    datasets_list_after_remove = run(
        f"az iot ops ns asset custom dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    remaining_dataset_names = [dataset["name"] for dataset in datasets_list_after_remove]
    assert dataset_name_1 not in remaining_dataset_names


def test_namespace_opcua_asset_dataset_lifecycle_operations(asset_factory):
    """Test complete lifecycle of OPCUA asset dataset and datapoint operations."""
    # Setup from shared fixtures
    info = asset_factory("opcua")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    dataset_name_1 = f"dataset{generate_random_string(6, force_lower=True)}"
    dataset_name_2 = f"dataset2{generate_random_string(6, force_lower=True)}"
    datapoint_name_1 = f"dp1-{generate_random_string(6, force_lower=True)}"
    datapoint_name_2 = f"dp2-{generate_random_string(6, force_lower=True)}"

    # 1. CREATE DATASET
    dataset_destinations = "topic=factory/opcua/temperature qos=Qos1 retain=Keep ttl=3600"

    # Add OPCUA asset dataset with specific OPCUA parameters
    start_instance = "ns=2;i=1001"
    dataset_result = run(
        f"az iot ops ns asset opcua dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {dataset_destinations} "
        f"--publish-int 1000 "
        f"--sampling-int 500 "
        f"--queue-size 10 "
        f"--key-frame-count 5 "
        f"--start-inst \"{start_instance}\" "
    )

    assert_dataset_properties(
        dataset_result,
        name=dataset_name_1,
        asset_type="opcua",
        publishing_interval=1000,
        opcua_configuration={"startInstance": start_instance},
    )

    # 2. LIST DATASETS
    datasets_list = run(
        f"az iot ops ns asset opcua dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    dataset_names = [dataset["name"] for dataset in datasets_list]
    assert dataset_name_1 in dataset_names
    assert len(datasets_list) >= 1

    # 3. SHOW DATASET
    shown_dataset = run(
        f"az iot ops ns asset opcua dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    assert_dataset_properties(
        shown_dataset,
        name=dataset_name_1,
        asset_type="opcua",
        publishing_interval=1000,
    )

    # 4. UPDATE DATASET
    updated_data_source = "ns=2;i=1002"
    updated_destinations = "topic=factory/opcua/temperature_v2 qos=Qos0 retain=Never ttl=1800"

    updated_dataset = run(
        f"az iot ops ns asset opcua dataset update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source \"{updated_data_source}\" "
        f"--destination {updated_destinations} "
        f"--publish-int 2000 "
        f"--sampling-int 1000 "
        f"--queue-size 20"
    )

    assert_dataset_properties(
        updated_dataset,
        name=dataset_name_1,
        data_source=updated_data_source,
        asset_type="opcua",
        publishing_interval=2000,
    )

    # 5a. TEST DATASET REPLACE FUNCTIONALITY
    # Replace dataset with --replace flag
    replaced_data_source = "ns=2;i=1003"

    replaced_dataset = run(
        f"az iot ops ns asset opcua dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source \"{replaced_data_source}\" "
        f"--publish-int 3000 --replace"
    )

    assert_dataset_properties(
        replaced_dataset,
        name=dataset_name_1,
        data_source=replaced_data_source,
        asset_type="opcua",
        publishing_interval=3000
    )

    # 5. TEST MULTIPLE DATASETS
    data_source = "ns=5;i=1005"

    dataset = run(
        f"az iot ops ns asset opcua dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_2} "
        f"--data-source \"{data_source}\" "
        f"--publish-int 3000 --replace"
    )

    assert_dataset_properties(
        dataset,
        name=dataset_name_2,
        data_source=data_source,
        asset_type="opcua",
        publishing_interval=3000
    )

    # 6. ADD DATASET DATAPOINTS
    # Add first datapoint
    datapoint_data_source_1 = "ns=2;i=2001"

    datapoint_result_1 = run(
        f"az iot ops ns asset opcua datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_1} --data-source \"{datapoint_data_source_1}\" "
        f"--queue-size 5 --sampling-int 250"
    )

    assert_point_properties(
        datapoint_result_1,
        name=datapoint_name_1,
        data_source=datapoint_data_source_1
    )

    # Add second datapoint
    datapoint_data_source_2 = "ns=2;i=2002"

    datapoint_result_2 = run(
        f"az iot ops ns asset opcua datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_2} --data-source \"{datapoint_data_source_2}\" "
        f"--queue-size 3 --sampling-int 500"
    )

    assert_point_properties(
        datapoint_result_2,
        name=datapoint_name_2,
        data_source=datapoint_data_source_2
    )

    # 7. LIST DATASET DATAPOINTS
    datapoints_list = wait_for_expected_count(
        list_cmd=(
            f"az iot ops ns asset opcua datapoint list --asset {asset_name} "
            f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1}"
        ),
        expected_count=2,
        expected_names=[datapoint_name_1, datapoint_name_2],
        reissue_cmds={
            datapoint_name_1: (
                f'az iot ops ns asset opcua datapoint add --asset {asset_name} '
                f'--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} '
                f'--name {datapoint_name_1} --data-source "{datapoint_data_source_1}"'
            ),
            datapoint_name_2: (
                f'az iot ops ns asset opcua datapoint add --asset {asset_name} '
                f'--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} '
                f'--name {datapoint_name_2} --data-source "{datapoint_data_source_2}"'
            ),
        },
    )

    assert len(datapoints_list) >= 2

    # 8. TEST DATAPOINT REPLACE FUNCTIONALITY
    # Replace first datapoint with --replace flag
    replaced_datapoint_data_source = "ns=2;i=2003"

    replaced_datapoint = run(
        f"az iot ops ns asset opcua datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_1} --data-source \"{replaced_datapoint_data_source}\" "
        f"--queue-size 15 --sampling-int 100 --replace"
    )

    assert_point_properties(
        replaced_datapoint,
        name=datapoint_name_1,
        data_source=replaced_datapoint_data_source
    )

    # 9. REMOVE DATASET DATAPOINT
    run(
        f"az iot ops ns asset opcua datapoint remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1} "
        f"--name {datapoint_name_2}"
    )

    # Verify datapoint removal
    datapoints_list_after_remove = run(
        f"az iot ops ns asset opcua datapoint list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name_1}"
    )

    remaining_datapoint_names = [dp["name"] for dp in datapoints_list_after_remove]
    assert datapoint_name_1 in remaining_datapoint_names
    assert datapoint_name_2 not in remaining_datapoint_names

    # 10. REMOVE DATASET
    run(
        f"az iot ops ns asset opcua dataset remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    # Verify dataset removal
    datasets_list_after_remove = run(
        f"az iot ops ns asset opcua dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    remaining_dataset_names = [dataset["name"] for dataset in datasets_list_after_remove]
    assert dataset_name_1 not in remaining_dataset_names


def test_namespace_rest_asset_dataset_lifecycle_operations(asset_factory):
    """Test complete lifecycle of REST asset dataset operations."""
    # Setup from shared fixtures
    info = asset_factory("rest")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    dataset_name_1 = f"dataset{generate_random_string(6, force_lower=True)}"

    # 1. CREATE DATASET
    dataset_destinations = "topic=factory/rest/temperature qos=Qos1 retain=Keep ttl=3600"

    # Add REST asset dataset with specific REST parameters
    dataset_result = run(
        f"az iot ops ns asset rest dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {dataset_destinations} "
        f"--sampling-int 5000"
    )

    assert_dataset_properties(
        dataset_result,
        name=dataset_name_1,
        asset_type="rest",
    )

    # 2. LIST DATASETS
    datasets_list = run(
        f"az iot ops ns asset rest dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    dataset_names = [dataset["name"] for dataset in datasets_list]
    assert dataset_name_1 in dataset_names
    assert len(datasets_list) >= 1

    # 3. SHOW DATASET
    shown_dataset = run(
        f"az iot ops ns asset rest dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    assert_dataset_properties(
        shown_dataset,
        name=dataset_name_1,
        asset_type="rest",
    )

    # 4. UPDATE DATASET
    updated_destinations = "topic=factory/rest/temperature_v2 qos=Qos0 retain=Never ttl=1800"

    updated_dataset = run(
        f"az iot ops ns asset rest dataset update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {updated_destinations} "
        f"--sampling-int 10000"
    )

    assert_dataset_properties(
        updated_dataset,
        name=dataset_name_1,
        asset_type="rest",
    )

    # 5. TEST DATASET REPLACE FUNCTIONALITY
    # Replace dataset with --replace flag
    replaced_data_source = "/api/temperature/replaced"
    broker_destinations = "key=rest-data-cache"

    replaced_dataset = run(
        f"az iot ops ns asset rest dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source {replaced_data_source} --dest {broker_destinations} "
        f"--sampling-int 15000 --replace"
    )

    assert_dataset_properties(
        replaced_dataset,
        name=dataset_name_1,
        data_source=replaced_data_source,
        asset_type="rest",
    )

    # Verify the destination was updated
    shown_broker_dataset = run(
        f"az iot ops ns asset rest dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    # Check that destination target is BrokerStateStore
    destinations = shown_broker_dataset.get("destinations", [])
    assert len(destinations) == 1
    assert destinations[0]["target"] == "BrokerStateStore"
    assert destinations[0]["configuration"]["key"] == "rest-data-cache"

    # 7. TEST WITH MINIMAL CONFIGURATION
    # Test creating dataset with minimal parameters
    minimal_data_source = "/api/minimal"

    minimal_dataset = run(
        f"az iot ops ns asset rest dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source {minimal_data_source} --replace"
    )

    assert_dataset_properties(
        minimal_dataset,
        name=dataset_name_1,
        data_source=minimal_data_source,
        asset_type="rest"
    )

    # 8. REMOVE DATASET
    run(
        f"az iot ops ns asset rest dataset remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    # Verify dataset removal
    datasets_list_after_remove = run(
        f"az iot ops ns asset rest dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    remaining_dataset_names = [dataset["name"] for dataset in datasets_list_after_remove]
    assert dataset_name_1 not in remaining_dataset_names


def test_namespace_sse_asset_dataset_lifecycle_operations(asset_factory):
    """Test complete lifecycle of SSE asset dataset operations."""
    # Setup from shared fixtures
    info = asset_factory("sse")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    dataset_name_1 = f"dataset{generate_random_string(6, force_lower=True)}"

    # 1. CREATE DATASET
    dataset_destinations = "topic=factory/sse/temperature qos=Qos1 retain=Keep ttl=3600"

    # Add SSE asset dataset (NOTE: No sampling interval since SSE is event-driven)
    dataset_result = run(
        f"az iot ops ns asset sse dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {dataset_destinations}"
    )

    assert_dataset_properties(
        dataset_result,
        name=dataset_name_1,
        asset_type="sse",
    )

    # 2. LIST DATASETS
    datasets_list = run(
        f"az iot ops ns asset sse dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    dataset_names = [dataset["name"] for dataset in datasets_list]
    assert dataset_name_1 in dataset_names
    assert len(datasets_list) >= 1

    # 3. SHOW DATASET
    dataset_show = run(
        f"az iot ops ns asset sse dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    assert_dataset_properties(
        dataset_show,
        name=dataset_name_1,
        asset_type="sse",
    )

    # 4. UPDATE DATASET
    updated_destinations = "topic=factory/sse/temperature_v2 qos=Qos0 retain=Never ttl=1800"

    updated_dataset = run(
        f"az iot ops ns asset sse dataset update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {updated_destinations}"
    )

    assert_dataset_properties(
        updated_dataset,
        name=dataset_name_1,
        asset_type="sse",
    )

    # 5. TEST DATASET REPLACE FUNCTIONALITY
    # Replace dataset with --replace flag
    replaced_data_source = "/events/temperature/replaced"
    broker_destinations = "key=sse-data-cache"

    replaced_dataset = run(
        f"az iot ops ns asset sse dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source {replaced_data_source} --dest {broker_destinations} "
        f"--replace"
    )

    assert_dataset_properties(
        replaced_dataset,
        name=dataset_name_1,
        asset_type="sse",
    )

    # 6. SHOW REPLACED DATASET
    replaced_dataset_show = run(
        f"az iot ops ns asset sse dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    assert_dataset_properties(
        replaced_dataset_show,
        name=dataset_name_1,
        data_source=replaced_data_source,
        asset_type="sse",
    )

    # 7. CREATE ADDITIONAL DATASET
    dataset_name_2 = f"dataset2{generate_random_string(6, force_lower=True)}"
    dataset_2_destinations = "topic=factory/sse/pressure qos=Qos1 retain=Keep ttl=7200"

    dataset_2_result = run(
        f"az iot ops ns asset sse dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_2} "
        f"--data-source /events/pressure "
        f"--destination {dataset_2_destinations}"
    )

    assert_dataset_properties(
        dataset_2_result,
        name=dataset_name_2,
        data_source="/events/pressure",
        asset_type="sse",
    )

    # 8. REMOVE DATASET
    run(
        f"az iot ops ns asset sse dataset remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    # Verify dataset removal
    datasets_list_after_remove = run(
        f"az iot ops ns asset sse dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    remaining_dataset_names = [dataset["name"] for dataset in datasets_list_after_remove]
    assert dataset_name_1 not in remaining_dataset_names


def test_namespace_mqtt_asset_dataset_lifecycle_operations(asset_factory):
    """Test complete lifecycle of MQTT asset dataset operations."""
    # Setup from shared fixtures
    info = asset_factory("mqtt")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    dataset_name_1 = f"dataset{generate_random_string(6, force_lower=True)}"

    # 1. CREATE DATASET
    dataset_destinations = "topic=telemetry/mqtt/temperature qos=Qos1 retain=Keep ttl=3600"

    # Add MQTT asset dataset (NOTE: MQTT datasets support BrokerStateStore and MQTT destinations only, no events)
    dataset_result = run(
        f"az iot ops ns asset mqtt dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {dataset_destinations}"
    )

    assert_dataset_properties(
        dataset_result,
        name=dataset_name_1,
        asset_type="mqtt",
    )

    # 2. LIST DATASETS
    datasets_list = run(
        f"az iot ops ns asset mqtt dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    dataset_names = [dataset["name"] for dataset in datasets_list]
    assert dataset_name_1 in dataset_names
    assert len(datasets_list) >= 1

    # 3. SHOW DATASET
    dataset_show = run(
        f"az iot ops ns asset mqtt dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    assert_dataset_properties(
        dataset_show,
        name=dataset_name_1,
        asset_type="mqtt",
    )

    # 4. UPDATE DATASET
    updated_destinations = "topic=telemetry/mqtt/temperature_v2 qos=Qos0 retain=Never ttl=1800"

    updated_dataset = run(
        f"az iot ops ns asset mqtt dataset update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--destination {updated_destinations}"
    )

    assert_dataset_properties(
        updated_dataset,
        name=dataset_name_1,
        asset_type="mqtt",
    )

    # 5. TEST DATASET REPLACE FUNCTIONALITY
    # Replace dataset with --replace flag
    replaced_data_source = "factory/temperature/replaced"
    broker_destinations = "key=mqtt-data-cache"

    replaced_dataset = run(
        f"az iot ops ns asset mqtt dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1} "
        f"--data-source {replaced_data_source} --dest {broker_destinations} "
        f"--replace"
    )

    assert_dataset_properties(
        replaced_dataset,
        name=dataset_name_1,
        asset_type="mqtt",
    )

    # 6. SHOW REPLACED DATASET
    replaced_dataset_show = run(
        f"az iot ops ns asset mqtt dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    assert_dataset_properties(
        replaced_dataset_show,
        name=dataset_name_1,
        data_source=replaced_data_source,
        asset_type="mqtt",
    )

    # 7. CREATE ADDITIONAL DATASET
    dataset_name_2 = f"dataset2{generate_random_string(6, force_lower=True)}"
    dataset_2_destinations = "topic=telemetry/mqtt/pressure qos=Qos1 retain=Keep ttl=7200"

    dataset_2_result = run(
        f"az iot ops ns asset mqtt dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_2} "
        f"--data-source factory/pressure "
        f"--destination {dataset_2_destinations}"
    )

    assert_dataset_properties(
        dataset_2_result,
        name=dataset_name_2,
        data_source="factory/pressure",
        asset_type="mqtt",
    )

    # 8. REMOVE DATASET
    run(
        f"az iot ops ns asset mqtt dataset remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name_1}"
    )

    # Verify dataset removal
    datasets_list_after_remove = run(
        f"az iot ops ns asset mqtt dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )

    remaining_dataset_names = [dataset["name"] for dataset in datasets_list_after_remove]
    assert dataset_name_1 not in remaining_dataset_names


# ---------------------------------------------------------------------------
# Generalized dataset / datapoint commands — OPC UA (bundled metadata)
# ---------------------------------------------------------------------------

def test_generalized_dataset_lifecycle_opcua(asset_factory, tracked_files: List[str]):
    """Full lifecycle of generalized dataset + datapoint commands on an OPC UA asset.

    Flow:
      1. --show-template config  →  discover schema
      2. Fill connector-specific values in the returned template
      3. Use filled template as --dataset-config / --datapoint-config
      4. CRUD: add / show / list / update / remove
      5. Export round-trip
    """
    info = asset_factory("opcua")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    dataset_name = f"gen-ds-{generate_random_string(6, force_lower=True)}"
    dataset_name_2 = f"gen-ds2-{generate_random_string(6, force_lower=True)}"
    datapoint_name = f"gen-dp-{generate_random_string(6, force_lower=True)}"
    data_source = "ns=2;s=Temperature"
    dp_data_source = "ns=2;s=Temperature.Value"

    # 1. SHOW-TEMPLATE – dataset
    dataset_template = run(
        f"az iot ops ns asset dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {dataset_name} --show-template config"
    )
    assert isinstance(dataset_template, dict)
    assert "connectorType" in dataset_template
    assert "datasetConfig" in dataset_template

    dataset_config = dataset_template.copy()
    dataset_config["datasetConfig"]["datasetConfiguration"] = {
        "publishingInterval": 1000,
        "samplingInterval": 500,
        "queueSize": 5,
    }
    dataset_config["datasetConfig"].pop("destinations", None)
    dataset_config_file = _save_json_to_file(dataset_config, tracked_files)

    # 2. ADD dataset with config
    added_dataset = run(
        f"az iot ops ns asset dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {dataset_name} --data-source '{data_source}' "
        f"--dataset-config {dataset_config_file}"
    )
    assert_dataset_properties(
        added_dataset, name=dataset_name, data_source=data_source,
        opcua_configuration={"publishingInterval": 1000},
    )

    # 3. SHOW dataset
    shown_dataset = run(
        f"az iot ops ns asset dataset show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {dataset_name}"
    )
    assert_dataset_properties(shown_dataset, name=dataset_name, data_source=data_source)

    # 4. LIST datasets
    datasets_list = run(
        f"az iot ops ns asset dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )
    assert any(d["name"] == dataset_name for d in datasets_list)

    # 5. ADD a second dataset
    added_dataset_2 = run(
        f"az iot ops ns asset dataset add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {dataset_name_2} --data-source '{data_source}'"
    )
    assert_dataset_properties(added_dataset_2, name=dataset_name_2)
    dataset_names = [d["name"] for d in run(
        f"az iot ops ns asset dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )]
    assert dataset_name in dataset_names and dataset_name_2 in dataset_names

    # 6. UPDATE dataset
    updated_source = "ns=2;s=Temperature.Updated"
    dataset_config["datasetConfig"]["datasetConfiguration"]["publishingInterval"] = 2000
    updated_config_file = _save_json_to_file(dataset_config, tracked_files)
    updated_dataset = run(
        f"az iot ops ns asset dataset update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {dataset_name} --data-source '{updated_source}' "
        f"--dataset-config {updated_config_file}"
    )
    assert_dataset_properties(
        updated_dataset, name=dataset_name, data_source=updated_source,
        opcua_configuration={"publishingInterval": 2000},
    )

    # 7. SHOW-TEMPLATE – datapoint
    datapoint_template = run(
        f"az iot ops ns asset datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--dataset {dataset_name} --name {datapoint_name} "
        f"--data-source '{dp_data_source}' --show-template config"
    )
    assert isinstance(datapoint_template, dict)
    assert "connectorType" in datapoint_template
    assert "datapointConfig" in datapoint_template

    datapoint_config = datapoint_template.copy()
    datapoint_config["datapointConfig"]["datapointConfiguration"] = {
        "samplingInterval": 200,
        "queueSize": 3,
    }
    datapoint_config_file = _save_json_to_file(datapoint_config, tracked_files)

    # 8. ADD datapoint with config
    added_datapoints = run(
        f"az iot ops ns asset datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--dataset {dataset_name} --name {datapoint_name} "
        f"--data-source '{dp_data_source}' --datapoint-config {datapoint_config_file}"
    )
    assert_point_properties(added_datapoints, name=datapoint_name, data_source=dp_data_source)

    # 9. LIST datapoints
    dp_list = run(
        f"az iot ops ns asset datapoint list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name}"
    )
    assert any(dp["name"] == datapoint_name for dp in dp_list)

    # 10. REPLACE datapoint
    replaced_dp_source = "ns=2;s=Temperature.Replaced"
    replaced_datapoints = run(
        f"az iot ops ns asset datapoint add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--dataset {dataset_name} --name {datapoint_name} "
        f"--data-source '{replaced_dp_source}' --replace"
    )
    assert_point_properties(replaced_datapoints, name=datapoint_name, data_source=replaced_dp_source)

    # 11. EXPORT datasets
    export_result = run(
        f"az iot ops ns asset dataset export --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --output-dir /tmp --replace"
    )
    assert export_result["dataset_count"] >= 1
    tracked_files.append(export_result["file_path"])

    # 12. EXPORT datapoints
    dp_export_result = run(
        f"az iot ops ns asset datapoint export --asset {asset_name} "
        f"--dataset {dataset_name} --instance {instance_name} -g {resource_group} "
        f"--output-dir /tmp --replace"
    )
    assert dp_export_result["datapoint_count"] >= 1
    tracked_files.append(dp_export_result["file_path"])

    # 13. REMOVE datapoint
    run(
        f"az iot ops ns asset datapoint remove --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--dataset {dataset_name} --name {datapoint_name}"
    )
    dp_list_after = run(
        f"az iot ops ns asset datapoint list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --dataset {dataset_name}"
    )
    assert not any(dp["name"] == datapoint_name for dp in (dp_list_after or []))

    # 14. REMOVE datasets
    for ds in [dataset_name, dataset_name_2]:
        run(
            f"az iot ops ns asset dataset remove --asset {asset_name} "
            f"--instance {instance_name} -g {resource_group} --name {ds}"
        )
    remaining = [d["name"] for d in (run(
        f"az iot ops ns asset dataset list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    ) or [])]
    assert dataset_name not in remaining and dataset_name_2 not in remaining


# ---------------------------------------------------------------------------
# Generalized dataset / datapoint commands — MQTT (connector template required)
# ---------------------------------------------------------------------------

def test_generalized_dataset_lifecycle_mqtt(asset_factory, tracked_files: List[str]):
    """Generalized dataset + datapoint lifecycle on an MQTT asset.

    --show-template is attempted first. If no connector template is installed,
    the template step is skipped and basic add/update/remove is tested without config.
    """
    info = asset_factory("mqtt")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    dataset_name = f"gen-ds-{generate_random_string(6, force_lower=True)}"
    datapoint_name = f"gen-dp-{generate_random_string(6, force_lower=True)}"
    data_source = "mqtt/temperature"
    dp_data_source = "mqtt/temperature/value"

    base_cmd = f"--asset {asset_name} --instance {instance_name} -g {resource_group}"

    # 1. SHOW-TEMPLATE – dataset (best-effort)
    dataset_config_file = None
    dataset_template = _try_show_template(
        f"az iot ops ns asset dataset add {base_cmd} "
        f"--name {dataset_name} --show-template config"
    )
    if dataset_template:
        assert "connectorType" in dataset_template
        assert "datasetConfig" in dataset_template
        dataset_config_file = _save_json_to_file(dataset_template, tracked_files)

    # 2. ADD dataset
    add_cmd = (
        f"az iot ops ns asset dataset add {base_cmd} "
        f"--name {dataset_name} --data-source '{data_source}'"
    )
    if dataset_config_file:
        add_cmd += f" --dataset-config {dataset_config_file}"
    added_dataset = run(add_cmd)
    assert_dataset_properties(added_dataset, name=dataset_name, data_source=data_source)

    # 3. SHOW dataset
    shown = run(f"az iot ops ns asset dataset show {base_cmd} --name {dataset_name}")
    assert_dataset_properties(shown, name=dataset_name)

    # 4. LIST datasets
    datasets_list = run(f"az iot ops ns asset dataset list {base_cmd}")
    assert any(d["name"] == dataset_name for d in datasets_list)

    # 5. UPDATE dataset
    updated_source = "mqtt/temperature/updated"
    updated_dataset = run(
        f"az iot ops ns asset dataset update {base_cmd} "
        f"--name {dataset_name} --data-source {updated_source}"
    )
    assert_dataset_properties(updated_dataset, name=dataset_name, data_source=updated_source)

    # 6. SHOW-TEMPLATE – datapoint (best-effort)
    datapoint_config_file = None
    datapoint_template = _try_show_template(
        f"az iot ops ns asset datapoint add {base_cmd} "
        f"--dataset {dataset_name} --name {datapoint_name} "
        f"--data-source '{dp_data_source}' --show-template config"
    )
    if datapoint_template:
        assert "connectorType" in datapoint_template
        assert "datapointConfig" in datapoint_template
        datapoint_config_file = _save_json_to_file(datapoint_template, tracked_files)

    # 7. ADD datapoint
    dp_add_cmd = (
        f"az iot ops ns asset datapoint add {base_cmd} "
        f"--dataset {dataset_name} --name {datapoint_name} "
        f"--data-source '{dp_data_source}'"
    )
    if datapoint_config_file:
        dp_add_cmd += f" --datapoint-config {datapoint_config_file}"
    added_datapoints = run(dp_add_cmd)
    assert_point_properties(added_datapoints, name=datapoint_name, data_source=dp_data_source)

    # 8. LIST datapoints
    dp_list = run(f"az iot ops ns asset datapoint list {base_cmd} --dataset {dataset_name}")
    assert any(dp["name"] == datapoint_name for dp in dp_list)

    # 9. REMOVE datapoint
    run(
        f"az iot ops ns asset datapoint remove {base_cmd} "
        f"--dataset {dataset_name} --name {datapoint_name}"
    )
    dp_list_after = run(f"az iot ops ns asset datapoint list {base_cmd} --dataset {dataset_name}")
    assert not any(dp["name"] == datapoint_name for dp in (dp_list_after or []))

    # 10. REMOVE dataset
    run(f"az iot ops ns asset dataset remove {base_cmd} --name {dataset_name}")
    datasets_after = run(f"az iot ops ns asset dataset list {base_cmd}")
    assert not any(d["name"] == dataset_name for d in (datasets_after or []))
