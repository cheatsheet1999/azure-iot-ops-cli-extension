# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import json
import os
from knack.log import get_logger
from typing import Any, Dict, List, Optional, Union
from azure.cli.core.azclierror import (
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    InvalidArgumentValueError,
    FileOperationError
)
from .user_strings import (
    AUTH_REF_MISMATCH_ERROR,
    GENERAL_AUTH_REF_MISMATCH_ERROR,
    MISSING_USERPASS_REF_ERROR,
    REMOVED_CERT_REF_MSG,
    REMOVED_USERPASS_REF_MSG,
)
from ..orchestration.resources import Instances
from .common import ADRAuthModes
from ...util.id_tools import parse_resource_id

logger = get_logger(__name__)


def check_cluster_connectivity(cmd, resource: dict):
    """
    Uses the resource's extended location to get the cluster and checks connectivity.
    Use this for commands that require the cluster to be connected to succeed.

    resource: dict representing an object that has the extended location property.

    """
    connected_cluster = Instances(cmd=cmd).get_resource_map(resource).connected_cluster
    if not connected_cluster.connected:
        logger.warning(f"Cluster {connected_cluster.cluster_name} is not connected.")


def get_extended_location(
    cmd,
    instance_name: str,
    instance_resource_group: str,
    instance_subscription: Optional[str] = None,
) -> Dict[str, Optional[Union[str, Dict[str, str]]]]:
    """
    Returns the extended location object with cluster location.

    Will also check for instance existance and whether the associated cluster is connected.

    instance_name: str representing the instance name
    instance_resource_group: str representing the instance resource group
    instance_subscription: str representing the instance subscription
        (if it is different from the current one)
    """
    instance_provider = Instances(cmd=cmd, subscription_id=instance_subscription)
    # instance should exist
    instance = instance_provider.show(
        name=instance_name, resource_group_name=instance_resource_group
    )
    resource_map = instance_provider.get_resource_map(instance=instance)
    connected_cluster = resource_map.connected_cluster
    if not connected_cluster.connected:
        logger.warning(f"Cluster {connected_cluster.cluster_name} is not connected.")

    # for the new adr
    namespace = instance["properties"].get("adrNamespaceRef", {}).get("resourceId")
    if namespace:
        namespace = parse_resource_id(rid=namespace)

    return {
        "type": "CustomLocation",
        "name": instance["extendedLocation"]["name"],
        "cluster_location": connected_cluster.location,
        "namespace": namespace
    }


def get_namespace_for_instance(
    cmd,
    instance_name: str,
    instance_resource_group: str,
    instance_subscription: Optional[str] = None,
) -> Dict[str, str]:
    """
    Returns the namespace resource for the given instance.
    """
    instance_provider = Instances(cmd=cmd, subscription_id=instance_subscription)
    # instance should exist
    instance = instance_provider.show(
        name=instance_name, resource_group_name=instance_resource_group
    )
    namespace = instance["properties"].get("adrNamespaceRef", {}).get("resourceId")
    if not namespace:
        raise InvalidArgumentValueError(
            f"Instance {instance_name} does not have an Device Registry namespace associated with it. "
            "Please update your instance to use new Device Registry features."
        )

    return parse_resource_id(rid=namespace)


def get_instance_query(
    query: str,
    instance_name: Optional[str] = None,
    instance_resource_group: Optional[str] = None,
    project_away_custom_location: bool = True
) -> str:
    """
    Appends and returns query with instance filtering.
    """
    if any([instance_name, instance_resource_group]):
        instance_query = "Resources | where type =~ 'microsoft.iotoperations/instances' "
        if instance_name:
            instance_query += f"| where name =~ \"{instance_name}\" "
        if instance_resource_group:
            instance_query += f"| where resourceGroup =~ \"{instance_resource_group}\" "

        # make sure the custom location is extended
        if "| extend customLocation = tostring(extendedLocation.name)" not in query:
            query += " | extend customLocation = tostring(extendedLocation.name)"

        # fetch the custom location + join on innerunique. Then remove the extra customLocation1 generated
        query = (
            f"{instance_query}| extend customLocation = tostring(extendedLocation.name) "
            "| project customLocation | join kind=innerunique "
            f"({query}) on customLocation "
            "| project-away customLocation1"
        )
        if project_away_custom_location:
            query += ", customLocation"
    return query


def get_query(param_mapping: Dict[str, str], params: Dict[str, Union[str, bool]]) -> str:
    """
    Returns a query string based on the provided parameters and their mappings.

    Disabled is treated as a boolean and should not be in the param mapping.
    """
    query = []
    if "disabled" in params and params["disabled"] is not None:
        query.append(f"| where properties.enabled == {not params.pop('disabled')}")
    for param, value in params.items():
        # TODO: later, add in null support (ex: no os set)
        if value is not None:
            query.append(f"| where {param_mapping.get(param)} =~ \"{value}\"")

    return " ".join(query)


def get_default_dataset(asset: dict, dataset_name: str, create_if_none: bool = False):
    """
    Helper function to get or create a dataset from an asset by name.

    If the dataset is not found and create_if_none is True, a new empty dataset
    with the given name is created and appended to the asset's datasets list.

    Raises an error if the dataset is not found and create_if_none is False.
    """
    asset["properties"]["datasets"] = asset["properties"].get("datasets", [])
    datasets = asset["properties"]["datasets"]
    matched_datasets = [dset for dset in datasets if dset["name"] == dataset_name]
    # backward compat: assets created during the transition period may have a single
    # dataset with an empty name that represents the "default" dataset
    if not matched_datasets and dataset_name == "default":
        matched_datasets = [dset for dset in datasets if dset["name"] == ""]
    if not matched_datasets and create_if_none:
        matched_datasets = [{}]
        datasets.extend(matched_datasets)
    elif not matched_datasets:
        raise InvalidArgumentValueError(f"Dataset {dataset_name} not found in asset {asset['name']}.")
    matched_datasets[0]["name"] = dataset_name
    return matched_datasets[0]


def _detect_shell() -> str:
    """Return a short shell identifier: 'powershell', 'bash', 'zsh', 'cmd', or 'unknown'."""
    import os
    import sys

    # Unix-like shells set $SHELL
    shell_path = os.environ.get("SHELL", "")
    if "zsh" in shell_path:
        return "zsh"
    if "bash" in shell_path:
        return "bash"
    # On Windows, reliably distinguishing PowerShell from CMD via environment
    # variables is not possible: PSModulePath is set system-wide for all processes
    # and PROMPT can be inherited by PowerShell from a parent CMD session.
    # Return a generic 'windows' identifier and show hints for both shells.
    if sys.platform == "win32":
        return "windows"
    # Non-Windows, non-Unix-shell: check for PowerShell Core (pwsh on Linux/macOS)
    if os.environ.get("PSModulePath"):
        return "powershell"
    return "unknown"


def _inline_json_quoting_hint() -> str:
    """Return a shell-specific quoting hint for inline JSON."""
    shell = _detect_shell()
    if shell == "windows":
        return (
            "Detected shell: Windows (PowerShell or CMD). "
            "In PowerShell, wrap in single quotes and escape inner double quotes:\n"
            "  --endpoint-config '{\\\"key\\\": \\\"value\\\"}'\n"
            "In CMD, escape each double quote with a backslash:\n"
            "  --endpoint-config {\\\"key\\\": \\\"value\\\"}"
        )
    if shell in ("bash", "zsh"):
        return (
            f"Detected shell: {shell}. "
            "Wrap the entire JSON value in single quotes (no escaping needed):\n"
            "  --endpoint-config '{\"key\": \"value\", \"nested\": {\"k\": 1}}'"
        )
    if shell == "powershell":  # PowerShell Core (pwsh) on Linux/macOS
        return (
            "Detected shell: PowerShell Core (pwsh). "
            "Wrap the JSON in single quotes and escape inner double quotes with backslash:\n"
            "  --endpoint-config '{\\\"key\\\": \\\"value\\\", \\\"nested\\\": {\\\"k\\\": 1}}'"
        )
    return (
        "Tip: in Bash/Zsh wrap the JSON in single quotes; "
        "in PowerShell escape inner double quotes with backslash (\\\"key\\\")."
    )


def process_additional_configuration(
    additional_configuration: Optional[str] = None,
    config_type: str = "additional",
    **_
) -> Optional[str]:
    """
    Validates and normalizes endpoint/asset configuration input.

    Accepts:
    - A file path to a JSON or YAML file (.json, .yaml, .yml)
    - An inline JSON string

    Always returns a stringified JSON (as required by the API's additionalConfiguration field).
    """
    from ...util import read_file_content

    if not additional_configuration:
        return

    logger.debug(f"Processing {config_type} configuration.")

    # Try to read as a file first
    try:
        file_content = read_file_content(additional_configuration)
        if not file_content:
            raise InvalidArgumentValueError("Given file is empty.")

        # Parse the already-read content directly — supports JSON and YAML transparently
        import json as _json
        import yaml
        parsed = None
        try:
            parsed = _json.loads(file_content)
        except _json.JSONDecodeError:
            try:
                parsed = yaml.safe_load(file_content)
            except yaml.YAMLError as e:
                raise InvalidArgumentValueError(
                    f"{config_type.capitalize()} configuration file is not valid JSON or YAML: {e}"
                )
        return _json.dumps(parsed)

    except FileOperationError:
        # Not a file path — treat as inline JSON string
        logger.debug(f"Given {config_type} configuration is not a file, treating as inline JSON.")
        import json as _json
        try:
            _json.loads(additional_configuration)
            return additional_configuration
        except _json.JSONDecodeError as e:
            raise InvalidArgumentValueError(
                f"{config_type.capitalize()} configuration is not valid JSON.\n"
                f"{_inline_json_quoting_hint()}\n"
                f"Parse error: {e}"
            )


def _setup_certificate_authentication(
    auth_props: Dict[str, str],
    certificate_reference: str,
    key_reference: Optional[str] = None,
    intermediate_certificate_reference: Optional[str] = None,
) -> None:
    """Setup certificate-based authentication."""
    auth_props["method"] = ADRAuthModes.certificate.value

    x509_credentials = {"certificateSecretName": certificate_reference}

    if key_reference:
        x509_credentials["keySecretName"] = key_reference

    if intermediate_certificate_reference:
        x509_credentials["intermediateCertificatesSecretName"] = intermediate_certificate_reference

    auth_props["x509Credentials"] = x509_credentials
    if auth_props.pop("usernamePasswordCredentials", None):
        logger.warning(REMOVED_USERPASS_REF_MSG)

    return auth_props


def _setup_username_password_authentication(
    auth_props: Dict[str, str],
    username_reference: str,
    password_reference: str,
) -> None:
    """Setup username/password-based authentication."""
    auth_props["method"] = ADRAuthModes.userpass.value
    user_creds = auth_props.get("usernamePasswordCredentials", {})
    user_creds["usernameSecretName"] = username_reference
    user_creds["passwordSecretName"] = password_reference

    if not all([user_creds["usernameSecretName"], user_creds["passwordSecretName"]]):
        raise RequiredArgumentMissingError(MISSING_USERPASS_REF_ERROR)

    auth_props["usernamePasswordCredentials"] = user_creds
    if auth_props.pop("x509Credentials", None):
        logger.warning(REMOVED_CERT_REF_MSG)


def _setup_anonymous_authentication(auth_props: Dict[str, str]) -> None:
    """Setup anonymous authentication."""
    auth_props["method"] = ADRAuthModes.anonymous.value
    if auth_props.pop("x509Credentials", None):
        logger.warning(REMOVED_CERT_REF_MSG)
    if auth_props.pop("usernamePasswordCredentials", None):
        logger.warning(REMOVED_USERPASS_REF_MSG)


def process_authentication(
    auth_mode: Optional[str] = None,
    auth_props: Optional[Dict[str, str]] = None,
    certificate_reference: Optional[str] = None,
    key_reference: Optional[str] = None,
    intermediate_certificate_reference: Optional[str] = None,
    password_reference: Optional[str] = None,
    username_reference: Optional[str] = None
) -> Dict[str, str]:
    """
    Create an authentication object to be used by namespace devices and AEPs.

    This will follow one of following format:
    {
        "method": "Anonymous"
    }

    or

    {
        "method": "UsernamePassword",
        "usernamePasswordCredentials": {
            "passwordSecretName": "str",
            "usernameSecretName": "str"
        }
    }

    or

    {
        "method": "Certificate",
        "x509Credentials": {
            "certificateSecretName": "str",
            "keySecretName": "str",  # optional
            "intermediateCertificatesSecretName": "str"  # optional
        }
    }
    """
    if not auth_props:
        auth_props = {}

    # Validate that optional certificate fields are only used with required certificate_reference
    if (key_reference or intermediate_certificate_reference) and not certificate_reference:
        raise RequiredArgumentMissingError(
            "Certificate reference (--cert-ref) is required when using --key-ref or --intermediate-cert-ref."
        )

    # add checking for ensuring auth mode is set with proper params
    if certificate_reference and (username_reference or password_reference):
        raise MutuallyExclusiveArgumentError(AUTH_REF_MISMATCH_ERROR)

    if certificate_reference and auth_mode in [None, ADRAuthModes.certificate.value]:
        _setup_certificate_authentication(
            auth_props,
            certificate_reference,
            key_reference,
            intermediate_certificate_reference
        )
    elif (username_reference or password_reference) and auth_mode in [None, ADRAuthModes.userpass.value]:
        _setup_username_password_authentication(
            auth_props, username_reference, password_reference
        )
    elif auth_mode == ADRAuthModes.anonymous.value and not any(
        [certificate_reference, username_reference, password_reference]
    ):
        _setup_anonymous_authentication(auth_props)
    elif not auth_mode and not auth_props:
        auth_props["method"] = ADRAuthModes.anonymous.value
    elif any([auth_mode, certificate_reference, username_reference, password_reference]):
        raise MutuallyExclusiveArgumentError(GENERAL_AUTH_REF_MISMATCH_ERROR)

    return auth_props


def ensure_schema_structure(schema: dict, input_data: dict, name: Optional[str] = None):
    """
    Validates the input data against the provided schema using jsonschema.
    """
    from ...util.schema_validation import validate_data_against_schema

    validate_data_against_schema(schema, input_data, name=name)


def strip_nulls(obj: Any) -> Any:
    """Recursively remove None values from dicts/lists; also drops empty dicts from lists."""
    if isinstance(obj, dict):
        return {k: strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        stripped = [strip_nulls(v) for v in obj if v is not None]
        return [item for item in stripped if item != {}]
    return obj


def load_opcua_metadata_file() -> dict:
    """Load and return the bundled OPC UA connector metadata JSON file."""
    from azure.cli.core.azclierror import ValidationError

    schema_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "schemas",
        "opcua_connector_metadata.json",
    )
    if not os.path.exists(schema_file):
        raise ValidationError(f"Bundled OPC UA metadata file not found: {schema_file}")
    with open(schema_file, "r", encoding="utf-8") as f:
        return json.load(f)


def get_opcua_info(cmd, instance_name: str, instance_resource_group: str) -> dict:
    """Load bundled OPC UA metadata after verifying the feature is not disabled.

    Raises:
        ValidationError: If OPC UA mode is explicitly set to 'Disabled' on the instance.
        ResourceNotFoundError: If the instance or resource-group is not found (ARM 404).
    """
    from azure.cli.core.azclierror import ValidationError
    from ..orchestration.resources.instances import Instances

    instance = Instances(cmd=cmd).show(
        name=instance_name,
        resource_group_name=instance_resource_group,
    )
    opcua_mode = (
        instance.get("properties", {})
        .get("features", {})
        .get("opcua", {})
        .get("mode")
    )
    if opcua_mode == "Disabled":
        raise ValidationError(
            f"OPC UA connector is disabled for instance '{instance_name}'. "
            "Enable it before creating an OPC UA endpoint or asset.\n"
            f"  az iot ops update -n {instance_name} -g {instance_resource_group} "
            "--feature opcua.mode=Stable"
        )
    return load_opcua_metadata_file()


def _consolidate_warnings(warnings: List[str]) -> List[str]:
    """Merge all per-field 'required fields' warnings into a single combined warning."""
    _REQ_PREFIX = (
        "The following required fields have no default value; "
        "replace null with a real value before applying: "
    )
    req_fields: List[str] = []
    other: List[str] = []
    for w in warnings:
        if w.startswith(_REQ_PREFIX):
            req_fields.extend(w[len(_REQ_PREFIX):].split(", "))
        else:
            other.append(w)
    if req_fields:
        other.append(_REQ_PREFIX + ", ".join(req_fields))
    return other


def _resolve_ref(ref: str, root_schema: dict) -> Optional[dict]:
    """
    Resolve a $ref string against the root schema's ``definitions`` block.

    Only Draft-07-style ``#/definitions/...`` paths are supported.  Any other
    ref format (external URLs, named anchors, ``$defs`` pointers, etc.) is
    silently ignored and returns ``None``, matching the behaviour of the
    Fluent UI form library this schema feeds into.
    """
    if not isinstance(ref, str) or not ref.startswith("#/definitions/"):
        return None
    # "#/definitions/foo/bar" → ["definitions", "foo", "bar"]
    parts = ref[2:].split("/")
    node: Any = root_schema
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def _slim_oneof(schema, variants, mode, _warnings, _field_path, _root_schema):
    """Handle oneOf discriminated union variants for _slim_schema."""
    from .common import EndpointTemplateMode
    non_null_variants = [v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")]
    parent_keys = {k: v for k, v in schema.items() if k != "oneOf"}

    if mode == EndpointTemplateMode.SCHEMA.value and len(variants) > 1:
        # schema mode: preserve ALL variants including null so the user sees the full picture
        return {
            **parent_keys,
            "oneOf": [
                _slim_schema(v, mode=mode, _warnings=_warnings, _field_path=_field_path, _root_schema=_root_schema)
                for v in variants
            ],
        }

    # config mode (or only one real variant): collapse to first non-null
    chosen = non_null_variants[0] if non_null_variants else variants[0]
    if _warnings is not None and len(non_null_variants) > 1:
        # Try to detect the discriminator key so the warning names it.
        # Rule: one property key shared across all non-null variants whose value
        # is a const or single-element enum.
        discriminator = None
        try:
            candidate_keys = None
            for v in non_null_variants:
                v_props = v.get("properties", {})
                keys = {
                    k for k, s in v_props.items()
                    if isinstance(s, dict) and (
                        "const" in s
                        or (isinstance(s.get("enum"), list) and len(s["enum"]) == 1)
                    )
                }
                candidate_keys = keys if candidate_keys is None else candidate_keys & keys
            if candidate_keys and len(candidate_keys) == 1:
                discriminator = next(iter(candidate_keys))
        except Exception:
            pass

        if discriminator:
            chosen_val = (
                chosen.get("properties", {}).get(discriminator, {}).get("const")
                or (chosen.get("properties", {}).get(discriminator, {}).get("enum") or [None])[0]
            )
            label = f"'{discriminator}'" + (f" (selected: '{chosen_val}')" if chosen_val is not None else "")
        else:
            label = f"'{_field_path}'" if _field_path else "the root schema"
        _warnings.append(
            f"Field {label} has {len(non_null_variants)} oneOf variants; "
            "only the first was used. Run --show-template schema to see all options."
        )
    merged = {**parent_keys}
    for k, v in chosen.items():
        if k == "properties" and "properties" in merged:
            # merge variant properties into parent properties instead of overwriting
            merged["properties"] = {**merged["properties"], **v}
        else:
            merged[k] = v
    return _slim_schema(merged, mode=mode, _warnings=_warnings, _field_path=_field_path, _root_schema=_root_schema)


def _slim_allof(schema, mode, _warnings, _field_path, _root_schema):
    """Handle allOf for _slim_schema."""
    from .common import EndpointTemplateMode
    non_null_subs = [s for s in schema["allOf"] if isinstance(s, dict) and s.get("type") != "null"]
    parent_keys = {k: v for k, v in schema.items() if k != "allOf"}

    if mode == EndpointTemplateMode.SCHEMA.value:
        return {
            **parent_keys,
            "allOf": [
                _slim_schema(s, mode=mode, _warnings=_warnings, _field_path=_field_path, _root_schema=_root_schema)
                for s in schema["allOf"]
            ],
        }

    # config mode: merge all sub-schema properties into one object
    merged = {**parent_keys}
    for sub in non_null_subs:
        for k, v in sub.items():
            if k == "properties":
                merged.setdefault("properties", {}).update(v)
            elif k not in merged:
                merged[k] = v
    return _slim_schema(merged, mode=mode, _warnings=_warnings, _field_path=_field_path, _root_schema=_root_schema)


# Constraint keywords forwarded into schema-mode metadata dicts.
_SLIM_CONSTRAINT_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "enum", "pattern")


def _slim_object_props(schema, props, mode, _warnings, _field_path, _root_schema):
    """Handle object-with-properties branch of _slim_schema."""
    from .common import EndpointTemplateMode
    required_in_schema = schema.get("required", [])
    required_fields = set(required_in_schema) if mode == EndpointTemplateMode.CONFIG.value else set()
    result = {}
    null_required: List[str] = []
    for field, field_schema in props.items():
        slimmed = _slim_schema(
            field_schema,
            mode=mode,
            _warnings=_warnings,
            _field_path=f"{_field_path}.{field}" if _field_path else field,
            _root_schema=_root_schema,
        )
        if mode == EndpointTemplateMode.CONFIG.value and slimmed is None and field in required_fields:
            null_required.append(f"{_field_path}.{field}" if _field_path else field)
        result[field] = slimmed
    if null_required and _warnings is not None:
        _warnings.append(
            "The following required fields have no default value; "
            "replace null with a real value before applying: "
            + ", ".join(f"'{f}'" for f in null_required)
        )
    if mode == EndpointTemplateMode.SCHEMA.value and required_in_schema:
        result["required"] = required_in_schema
    return result


def _slim_array_items(schema, default, mode, _warnings, _field_path, _root_schema):
    """Handle array-with-items branch of _slim_schema."""
    from .common import EndpointTemplateMode
    slimmed_item = _slim_schema(
        schema["items"], mode=mode, _warnings=_warnings,
        _field_path=f"{_field_path}[]", _root_schema=_root_schema,
    )
    if mode == EndpointTemplateMode.SCHEMA.value:
        entry = {"type": "array", "default": default, "items": slimmed_item}
        for k in _SLIM_CONSTRAINT_KEYS:
            if k in schema:
                entry[k] = schema[k]
        return entry
    return [slimmed_item] if slimmed_item is not None else default


def _slim_scalar_leaf(schema, raw_type, default, mode):
    """Handle scalar leaf in _slim_schema."""
    from .common import EndpointTemplateMode
    if mode == EndpointTemplateMode.SCHEMA.value:
        entry = {"type": raw_type, "default": default}
        for k in _SLIM_CONSTRAINT_KEYS:
            if k in schema:
                entry[k] = schema[k]
        return entry
    return default


def _slim_schema(
    schema: dict,
    mode: str = "config",
    _warnings: Optional[List[str]] = None,
    _field_path: str = "",
    _root_schema: Optional[dict] = None,
) -> dict:
    """
    Converts a JSON Schema Draft-07 document into a user-friendly config template.

    modes:
      config  - Fields with a default are shown as the default value.
                Fields without a default are shown as null.
                Output is directly submittable as --endpoint-config.

      schema  - Every field includes a metadata dict with keys: type, default,
                and any constraints present (minimum, maximum, enum, pattern).
                Useful for discovering the full schema before crafting a config.

    Supported constructs (aligns with the Fluent UI v9 form library):
      - properties, nested objects, required
      - items (array of strings, string enums, or objects)
      - oneOf (discriminated unions; config mode collapses to first non-null variant
        and records a warning; schema mode preserves all variants including null)
      - allOf (merges properties in config mode; preserves structure in schema mode)
      - $ref with ``#/definitions/...`` paths (Draft-07 style only); other ref
        formats are silently ignored
      - const (rendered as a read-only value)
      - Validation keywords: minimum, maximum, exclusiveMinimum,
        exclusiveMaximum, enum, pattern

    Unsupported (silently ignored to match form library behaviour):
      - anyOf, if/then/else, not
      - additionalProperties, patternProperties
      - External $ref URLs, named anchors ($anchor / bare-fragment $id), $defs

    Args:
        schema: JSON schema dict to process.
        mode: 'config' or 'schema'.
        _warnings: mutable list collecting field paths with collapsed oneOf variants
            (config mode).
        _field_path: dot-separated path to the current field, used in warning messages.
        _root_schema: root schema passed unchanged through recursion for $ref resolution;
            set to ``schema`` on the first call.
    """
    from .common import EndpointTemplateMode
    if not isinstance(schema, dict):
        return schema

    # Capture root schema on first call for $ref resolution
    if _root_schema is None:
        _root_schema = schema

    # Resolve $ref before anything else; merge sibling keys per JSON Schema spec.
    # Only #/definitions/... paths are supported; others are silently dropped.
    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], _root_schema)
        if resolved is not None:
            merged = {**resolved, **{k: v for k, v in schema.items() if k != "$ref"}}
            return _slim_schema(
                merged, mode=mode, _warnings=_warnings, _field_path=_field_path, _root_schema=_root_schema
            )
        # Unresolvable ref — fall through with remaining sibling keys
        schema = {k: v for k, v in schema.items() if k != "$ref"}
        if not schema:
            return None

    # Resolve oneOf (discriminated unions).
    # anyOf is unsupported by the form library and is silently ignored.
    variants = schema.get("oneOf")
    if variants:
        return _slim_oneof(schema, variants, mode, _warnings, _field_path, _root_schema)

    # Resolve allOf
    if "allOf" in schema:
        return _slim_allof(schema, mode, _warnings, _field_path, _root_schema)

    # const — read-only field locked to a fixed value
    if "const" in schema:
        const_val = schema["const"]
        if mode == EndpointTemplateMode.SCHEMA.value:
            return {"type": "const", "const": const_val}
        return const_val

    props = schema.get("properties", {})
    raw_type = schema.get("type", "string")
    if isinstance(raw_type, list):
        non_null = [t for t in raw_type if t != "null"]
        raw_type = non_null[0] if non_null else "string"
    default = schema.get("default")

    if props:
        return _slim_object_props(schema, props, mode, _warnings, _field_path, _root_schema)

    if raw_type == "array" and "items" in schema:
        return _slim_array_items(schema, default, mode, _warnings, _field_path, _root_schema)

    return _slim_scalar_leaf(schema, raw_type, default, mode)
