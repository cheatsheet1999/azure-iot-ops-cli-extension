# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from typing import Optional

from knack.log import get_logger

from .providers.orchestration.resources import Instances

logger = get_logger(__name__)


def secretsync_enable(
    cmd,
    instance_name: str,
    resource_group_name: str,
    mi_user_assigned: str,
    keyvault_resource_id: str,
    spc_name: Optional[str] = None,
    skip_role_assignments: Optional[bool] = None,
    use_self_hosted_issuer: Optional[bool] = None,
    custom_role_id: Optional[str] = None,
    tags: Optional[dict] = None,
    **kwargs,
) -> dict:
    return Instances(cmd).enable_secretsync(
        name=instance_name,
        resource_group_name=resource_group_name,
        mi_user_assigned=mi_user_assigned,
        keyvault_resource_id=keyvault_resource_id,
        spc_name=spc_name,
        skip_role_assignments=skip_role_assignments,
        use_self_hosted_issuer=use_self_hosted_issuer,
        custom_role_id=custom_role_id,
        tags=tags,
        **kwargs,
    )


def secretsync_list(cmd, instance_name: str, resource_group_name: str) -> Optional[list[dict]]:
    return Instances(cmd).list_secretsync(
        name=instance_name,
        resource_group_name=resource_group_name,
    )


def secretsync_disable(cmd, instance_name: str, resource_group_name: str, confirm_yes: Optional[bool] = None, **kwargs):
    return Instances(cmd).disable_secretsync(
        name=instance_name,
        resource_group_name=resource_group_name,
        confirm_yes=confirm_yes,
        **kwargs,
    )


def secretsync_secret_set(
    cmd,
    instance_name: str,
    resource_group_name: str,
    secret_sync_name: str,
    secret_map: list,
    **kwargs,
) -> dict:
    return Instances(cmd).set_secretsync_secret(
        name=instance_name,
        resource_group_name=resource_group_name,
        secret_sync_name=secret_sync_name,
        secret_map=secret_map,
        **kwargs,
    )


def secretsync_secret_list(
    cmd,
    instance_name: str,
    resource_group_name: str,
    secret_sync_name: str,
) -> list[dict]:
    return Instances(cmd).list_secretsync_secrets(
        name=instance_name,
        resource_group_name=resource_group_name,
        secret_sync_name=secret_sync_name,
    )


def secretsync_secret_remove(
    cmd,
    instance_name: str,
    resource_group_name: str,
    secret_sync_name: str,
    secret_name: str,
    confirm_yes: Optional[bool] = None,
    **kwargs,
) -> Optional[dict]:
    return Instances(cmd).remove_secretsync_secret(
        name=instance_name,
        resource_group_name=resource_group_name,
        secret_sync_name=secret_sync_name,
        secret_name=secret_name,
        confirm_yes=confirm_yes,
        **kwargs,
    )
