# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from typing import Iterable, Optional

from .common import DEFAULT_DATAFLOW_PROFILE
from .providers.orchestration.resources.dataflow_graphs import DataFlowGraphs


def show_dataflow_graph(
    cmd,
    dataflow_graph_name: str,
    instance_name: str,
    resource_group_name: str,
    profile_name: str = DEFAULT_DATAFLOW_PROFILE,
) -> dict:
    return DataFlowGraphs(cmd).show(
        name=dataflow_graph_name,
        dataflow_profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
    )


def list_dataflow_graphs(
    cmd,
    instance_name: str,
    resource_group_name: str,
    profile_name: str = DEFAULT_DATAFLOW_PROFILE,
) -> Iterable[dict]:
    return DataFlowGraphs(cmd).list(
        dataflow_profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
    )


def apply_dataflow_graph(
    cmd,
    dataflow_graph_name: str,
    instance_name: str,
    resource_group_name: str,
    config_file: str,
    profile_name: str = DEFAULT_DATAFLOW_PROFILE,
    **kwargs: dict,
) -> dict:
    return DataFlowGraphs(cmd).apply(
        name=dataflow_graph_name,
        dataflow_profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
        config_file=config_file,
        **kwargs,
    )


def delete_dataflow_graph(
    cmd,
    dataflow_graph_name: str,
    instance_name: str,
    resource_group_name: str,
    profile_name: str = DEFAULT_DATAFLOW_PROFILE,
    confirm_yes: Optional[bool] = None,
    **kwargs: dict,
):
    return DataFlowGraphs(cmd).delete(
        name=dataflow_graph_name,
        dataflow_profile_name=profile_name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
        confirm_yes=confirm_yes,
        **kwargs,
    )
