# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from typing import List
import pytest

from ...generators import generate_random_string
from ...helpers import run
from .namespace_helpers import (
    create_config_file, assert_stream_properties, check_destinations,
    _save_json_to_file, _try_show_template
)


pytestmark = [pytest.mark.rpsaas, pytest.mark.long_running]


def test_namespace_custom_asset_stream_lifecycle_operations(
    asset_factory, tracked_files: List[str]
):
    """Test complete lifecycle of custom asset stream operations."""
    # Setup from shared fixtures
    info = asset_factory("custom")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    stream_name = f"stream-{generate_random_string(6, force_lower=True)}"

    # 1. CREATE STREAM
    custom_config_path, custom_config = create_config_file(tracked_files)
    stream_destinations = "topic=factory/custom/streams qos=Qos1 retain=Never ttl=3600"

    stream_result = run(
        f"az iot ops ns asset custom stream add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {stream_name} "
        f"--config {custom_config_path} --destination {stream_destinations}"
    )

    assert_stream_properties(
        stream_result,
        name=stream_name,
        custom_configuration=custom_config,
    )

    # 2. LIST STREAMS
    streams_list = run(
        f"az iot ops ns asset custom stream list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    assert len(streams_list) >= 1
    stream_names = [stream["name"] for stream in streams_list]
    assert stream_name in stream_names

    # 3. SHOW STREAM
    stream_show = run(
        f"az iot ops ns asset custom stream show --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {stream_name}"
    )

    assert_stream_properties(
        stream_show,
        name=stream_name
    )

    # 4. UPDATE STREAM
    updated_custom_config_path, updated_custom_config = create_config_file(tracked_files)

    updated_stream = run(
        f"az iot ops ns asset custom stream update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {stream_name} "
        f"--config {updated_custom_config_path}"
    )

    assert_stream_properties(
        updated_stream,
        name=stream_name,
        custom_configuration=updated_custom_config,
    )

    # 5. CREATE STREAM WITH REPLACE
    replaced_custom_config_path, replaced_custom_config = create_config_file(tracked_files)
    replaced_stream = run(
        f"az iot ops ns asset custom stream add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {stream_name} "
        f"--config {replaced_custom_config_path} --replace"
    )

    assert_stream_properties(
        replaced_stream,
        name=stream_name,
        custom_configuration=replaced_custom_config,
    )

    # 6. REMOVE STREAM
    run(
        f"az iot ops ns asset custom stream remove --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {stream_name}"
    )

    # Verify removal by listing
    remaining_streams = run(
        f"az iot ops ns asset custom stream list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    remaining_stream_names = [stream["name"] for stream in remaining_streams]
    assert stream_name not in remaining_stream_names


def test_namespace_media_asset_stream_lifecycle_operations(asset_factory):
    """Test complete lifecycle of media asset stream operations with all stream types."""
    # Setup from shared fixtures
    info = asset_factory("media")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]

    # Test all media stream types
    stream_test_cases = [
        {
            "name": f"snapshot-mqtt-{generate_random_string(4, force_lower=True)}",
            "task_type": "snapshot-to-mqtt",
            "format": "jpeg",
            "snapshots_per_second": 1,
            "disable_autostart": True,
            "destinations": "topic=factory/media/snapshots qos=Qos1 retain=Keep ttl=1800"
        },
        {
            "name": f"snapshot-fs-{generate_random_string(4, force_lower=True)}",
            "task_type": "snapshot-to-fs",
            "format": "png",
            "snapshots_per_second": 2,
            "path": "/media/snapshots"
        },
        {
            "name": f"clip-fs-{generate_random_string(4, force_lower=True)}",
            "task_type": "clip-to-fs",
            "format": "mp4",
            "duration": 300,
            "path": "/media/clips",
            "disable_autostart": True,
            "destinations": "path=/media/clips/recordings"
        },
        {
            "name": f"rtsp-stream-{generate_random_string(4, force_lower=True)}",
            "task_type": "stream-to-rtsp",
            "server_address": "media-server.local",
            "server_port": 8554,
            "server_path": "/live/stream1",
            "server_username": "streamuser",
            "server_password": "streampass"
        },
        {
            "name": f"rtsps-stream-{generate_random_string(4, force_lower=True)}",
            "task_type": "stream-to-rtsps",
            "server_address": "secure-media-server.local",
            "server_port": 322,
            "server_path": "/secure/stream",
            "server_certificate": "/path/to/cert.pem"
        }
    ]

    param_map = {
        "name": "--name",
        "task_type": "--task-type",
        "format": "--format",
        "snapshots_per_second": "--snapshots-per-sec",
        "duration": "--duration",
        "path": "--path",
        "server_address": "--media-server-address",
        "server_port": "--media-server-port",
        "server_path": "--media-server-path",
        "server_username": "--media-server-user",
        "server_password": "--media-server-pass",
        "server_certificate": "--media-server-cert",
        "destinations": "--destination",
        "disable_autostart": "--disable-autostart"
    }

    created_streams = []

    # 1. CREATE ALL STREAM TYPES
    for test_case in stream_test_cases:

        # Build the command based on stream type
        command = (
            f"az iot ops ns asset media stream add --asset {asset_name} --instance {instance_name} "
            f"-g {resource_group}"
        )
        for param, value in test_case.items():
            cli_flag = param_map.get(param)
            if cli_flag:
                command += f" {cli_flag} {value}"

        stream_result = run(command)

        assert_media_stream_properties(
            stream_result,
            name=test_case["name"],
            task_type=test_case["task_type"],
        )

        created_streams.append(test_case["name"])

    # 2. LIST ALL STREAMS
    streams_list = run(
        f"az iot ops ns asset media stream list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    assert len(streams_list) >= len(created_streams)
    stream_names = [stream["name"] for stream in streams_list]
    for created_stream in created_streams:
        assert created_stream in stream_names

    # 3. SHOW EACH STREAM TYPE
    for stream_name in created_streams:
        stream_show = run(
            f"az iot ops ns asset media stream show --asset {asset_name} --instance {instance_name} "
            f"-g {resource_group} --name {stream_name}"
        )

        assert_media_stream_properties(
            stream_show,
            name=stream_name
        )

    # 4. UPDATE DIFFERENT STREAM TYPES

    # Update snapshot-to-mqtt stream format
    snapshot_mqtt_stream = created_streams[0]
    updated_snapshot = run(
        f"az iot ops ns asset media stream update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {snapshot_mqtt_stream} --format bmp --snapshots-per-sec 3"
    )

    assert_media_stream_properties(
        updated_snapshot,
        name=snapshot_mqtt_stream
    )

    # Update clip stream duration and path
    clip_stream = created_streams[2]
    updated_clip = run(
        f"az iot ops ns asset media stream update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {clip_stream} --duration 600 --path /updated/clips"
    )

    assert_media_stream_properties(
        updated_clip,
        name=clip_stream
    )

    # Update RTSP stream server configuration
    rtsp_stream = created_streams[3]
    updated_rtsp = run(
        f"az iot ops ns asset media stream update --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {rtsp_stream} --media-server-address 192.168.1.250 --media-server-port 8555"
    )

    assert_media_stream_properties(
        updated_rtsp,
        name=rtsp_stream
    )

    # 5. CREATE STREAM WITH REPLACE
    replaced_stream_name = created_streams[0]
    replaced_stream = run(
        f"az iot ops ns asset media stream add --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group} --name {replaced_stream_name} --task-type snapshot-to-mqtt "
        f"--format tiff --snapshots-per-sec 5 --replace"
    )

    assert_media_stream_properties(
        replaced_stream,
        name=replaced_stream_name,
        task_type="snapshot-to-mqtt"
    )

    # 6. REMOVE STREAMS
    for stream_name in created_streams:
        run(
            f"az iot ops ns asset media stream remove --asset {asset_name} --instance {instance_name} "
            f"-g {resource_group} --name {stream_name}"
        )

    # Verify removal by listing
    remaining_streams = run(
        f"az iot ops ns asset media stream list --asset {asset_name} --instance {instance_name} "
        f"-g {resource_group}"
    )

    remaining_stream_names = [stream["name"] for stream in remaining_streams]
    for removed_stream in created_streams:
        assert removed_stream not in remaining_stream_names


def assert_media_stream_properties(result, **expected):
    """Verify media stream properties match expected values."""
    assert result["name"] == expected["name"]

    if "task_type" in expected:
        # Verify the task type is set in the stream configuration
        stream_config = result.get("streamConfiguration")
        if stream_config:
            import json
            config_dict = json.loads(stream_config) if isinstance(stream_config, str) else stream_config
            assert config_dict.get("taskType") == expected["task_type"]

    if "destinations" in expected:
        check_destinations(result, expected)


# ---------------------------------------------------------------------------
# Generalized (connector-agnostic) stream commands
# ---------------------------------------------------------------------------


def test_generalized_stream_lifecycle_custom(asset_factory, tracked_files: List[str]):
    """Generalized stream lifecycle on a custom asset.

    A connector template must exist in the instance for --show-template / --stream-config
    to resolve connector metadata. When no template is installed, --show-template returns an
    empty dict and the test exercises the metadata-free path (no config payload).
    """
    info = asset_factory("custom")
    asset_name = info["name"]
    instance_name = info["instanceName"]
    resource_group = info["resourceGroup"]
    stream_name = f"gen-stream-{generate_random_string(6, force_lower=True)}"
    stream_name_2 = f"gen-stream2-{generate_random_string(6, force_lower=True)}"

    # 1. SHOW-TEMPLATE - stream (may be empty when no connector template installed)
    stream_template = _try_show_template(
        f"az iot ops ns asset stream add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {stream_name} --show-template config"
    )

    if not stream_template:
        pytest.skip(
            "Generalized stream commands require connector metadata; no connector template "
            "supporting streams is installed for this connector."
        )
    assert "connectorType" in stream_template
    assert "streamConfig" in stream_template
    stream_config = stream_template.copy()
    stream_config["streamConfig"].pop("destinations", None)
    stream_config_file = _save_json_to_file(stream_config, tracked_files)
    stream_config_arg = f"--stream-config {stream_config_file}"

    # 2. ADD stream
    added_stream = run(
        f"az iot ops ns asset stream add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {stream_name} {stream_config_arg}"
    )
    assert_stream_properties(added_stream, name=stream_name)

    # 3. SHOW stream
    shown_stream = run(
        f"az iot ops ns asset stream show --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {stream_name}"
    )
    assert_stream_properties(shown_stream, name=stream_name)

    # 4. LIST streams
    stream_list = run(
        f"az iot ops ns asset stream list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )
    assert any(s["name"] == stream_name for s in stream_list)

    # 5. ADD a second stream (minimal)
    added_stream_2 = run(
        f"az iot ops ns asset stream add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --name {stream_name_2}"
    )
    assert_stream_properties(added_stream_2, name=stream_name_2)
    stream_names = [s["name"] for s in run(
        f"az iot ops ns asset stream list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    )]
    assert stream_name in stream_names and stream_name_2 in stream_names

    # 6. UPDATE stream (type reference)
    updated_stream = run(
        f"az iot ops ns asset stream update --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {stream_name} --type-ref myTypeRef"
    )
    assert_stream_properties(updated_stream, name=stream_name)
    assert updated_stream.get("typeRef") == "myTypeRef"

    # 7. REPLACE stream
    replaced_stream = run(
        f"az iot ops ns asset stream add --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} "
        f"--name {stream_name} --replace"
    )
    assert_stream_properties(replaced_stream, name=stream_name)

    # 8. EXPORT streams
    export_result = run(
        f"az iot ops ns asset stream export --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group} --output-dir /tmp --replace"
    )
    assert export_result["stream_count"] >= 1
    tracked_files.append(export_result["file_path"])

    # 9. REMOVE streams
    for stream in [stream_name, stream_name_2]:
        run(
            f"az iot ops ns asset stream remove --asset {asset_name} "
            f"--instance {instance_name} -g {resource_group} --name {stream}"
        )
    remaining = [s["name"] for s in (run(
        f"az iot ops ns asset stream list --asset {asset_name} "
        f"--instance {instance_name} -g {resource_group}"
    ) or [])]
    assert stream_name not in remaining and stream_name_2 not in remaining
