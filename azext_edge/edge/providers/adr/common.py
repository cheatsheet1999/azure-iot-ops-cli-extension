# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from enum import Enum
from ...common import ListableEnum


class DestinationQos(ListableEnum):
    """Quality of Service for MQTT destinations."""
    qos0 = "Qos0"
    qos1 = "Qos1"


class ActionType(Enum):
    """Type of action for management group actions."""
    call = "Call"
    read = "Read"
    write = "Write"


class FileType(ListableEnum):
    """
    Supported file types/extensions for bulk asset operations.
    """

    json = "json"
    csv = "csv"
    yaml = "yaml"


class ADRAuthModes(Enum):
    """
    Authentication modes for asset endpoints/devices
    """

    anonymous = "Anonymous"
    certificate = "Certificate"
    userpass = "UsernamePassword"


class AEPTypes(ListableEnum):
    """Asset Endpoint Profile (connector) Types"""

    opcua = "Microsoft.OpcUa"
    onvif = "Microsoft.Onvif"


class TopicRetain(ListableEnum):
    """Set the retain flag for messages published to an MQTT broker."""

    keep = "Keep"
    never = "Never"


class EndpointTemplateMode(ListableEnum):
    """
    Controls how --show-template renders the endpoint configuration template.

    config  - Fields with a default value are shown as the default value.
              Fields with no default are shown as null.
              Output is directly submittable as --endpoint-config.

    schema  - Every field includes full metadata: type, default value,
              and constraints (minimum, maximum, enum, pattern) where available.
              Useful for understanding the full schema before crafting a config.
    """

    CONFIG = "config"
    SCHEMA = "schema"
