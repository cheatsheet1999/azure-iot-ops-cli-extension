# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from typing import Dict, List, Optional

from knack.log import get_logger

from ...util.az_client import (
    get_eventgrid_mgmt_client,
    get_iotops_mgmt_client,
    get_registry_mgmt_client,
)
from ...util.queryable import Queryable
from .permissions import PermissionManager

logger = get_logger(__name__)


class MgmtActions(Queryable):
    """Provider for management actions (outer loop) enable/disable operations."""

    def __init__(self, cmd, subscription_id: Optional[str] = None):
        super().__init__(cmd=cmd, subscription_id=subscription_id)
        self.iotops_mgmt_client = get_iotops_mgmt_client(
            subscription_id=self.default_subscription_id,
        )
        self.eventgrid_mgmt_client = get_eventgrid_mgmt_client(
            subscription_id=self.default_subscription_id,
        )
        self.registry_mgmt_client = get_registry_mgmt_client(
            subscription_id=self.default_subscription_id,
        )
        self.permission_manager = PermissionManager(self.default_subscription_id)

    def enable(
        self,
        name: str,
        resource_group_name: str,
        eg_resource_id: str,
        mi_user_assigned: Optional[str] = None,
        eg_client_group: Optional[str] = None,
        adr_role_ids: Optional[List[str]] = None,
        ops_role_ids: Optional[List[str]] = None,
        skip_role_assignments: Optional[bool] = None,
        dataflow_profile: Optional[str] = None,
        **kwargs,
    ) -> Dict:
        """Enable management actions for an IoT Operations instance.

        Bootstraps the outer loop infrastructure across Event Grid, ADR, and AIO domains.
        """
        raise NotImplementedError("mgmt-actions enable is not yet implemented")

    def disable(
        self,
        name: str,
        resource_group_name: str,
        confirm_yes: Optional[bool] = None,
        **kwargs,
    ) -> None:
        """Disable management actions for an IoT Operations instance.

        Tears down outer loop resources: dataflow graph, response dataflow, EG dataflow endpoint,
        EG topic space/permission bindings, and ADR namespace management endpoint entry.
        """
        raise NotImplementedError("mgmt-actions disable is not yet implemented")
