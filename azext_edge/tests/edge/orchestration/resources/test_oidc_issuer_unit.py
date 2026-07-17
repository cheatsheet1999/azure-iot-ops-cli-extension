# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import requests
import responses

from azext_edge.edge.providers.orchestration.resources.instances import (
    OIDC_DISCOVERY_MAX_RESPONSE_BYTES,
    OIDC_DISCOVERY_PATH,
    resolve_oidc_issuer,
)


def test_resolve_oidc_issuer_uses_exact_public_discovery(mocked_responses: responses, mocker):
    arm_issuer = "https://issuer.example/cluster"
    mocked_responses.add(
        method=responses.GET,
        url=f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        json={"issuer": arm_issuer},
        status=200,
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    warning.assert_not_called()


def test_resolve_oidc_issuer_corrects_one_trailing_slash(mocked_responses: responses, mocker):
    arm_issuer = "https://issuer.example/cluster/"
    discovery_issuer = arm_issuer[:-1]
    mocked_responses.add(
        method=responses.GET,
        url=f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        status=404,
    )
    mocked_responses.add(
        method=responses.GET,
        url=f"{discovery_issuer}{OIDC_DISCOVERY_PATH}",
        json={"issuer": discovery_issuer},
        status=200,
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == discovery_issuer
    assert [call.request.url for call in mocked_responses.calls] == [
        f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        f"{discovery_issuer}{OIDC_DISCOVERY_PATH}",
    ]
    warning.assert_called_once()


def test_resolve_oidc_issuer_keeps_arm_issuer_for_malformed_discovery(mocked_responses: responses, mocker):
    arm_issuer = "https://issuer.example/cluster"
    mocked_responses.add(
        method=responses.GET,
        url=f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        body="not-json",
        status=200,
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    warning.assert_called_once()


def test_resolve_oidc_issuer_rejects_more_than_one_trailing_slash(mocked_responses: responses, mocker):
    arm_issuer = "https://issuer.example/cluster//"
    discovery_issuer = arm_issuer.rstrip("/")
    for discovery_url in (
        f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        f"{arm_issuer[:-1]}{OIDC_DISCOVERY_PATH}",
    ):
        mocked_responses.add(
            method=responses.GET,
            url=discovery_url,
            json={"issuer": discovery_issuer},
            status=200,
        )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    warning.assert_called_once()


def test_resolve_oidc_issuer_rejects_non_https_issuer(mocker):
    arm_issuer = "http://issuer.example/cluster"
    request_get = mocker.patch(
        "azext_edge.edge.providers.orchestration.resources.instances.requests.get",
        autospec=True,
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    request_get.assert_not_called()
    warning.assert_called_once()


def test_resolve_oidc_issuer_keeps_arm_issuer_for_malformed_issuer_url(mocker):
    arm_issuer = "https://[oops"
    request_get = mocker.patch(
        "azext_edge.edge.providers.orchestration.resources.instances.requests.get",
        autospec=True,
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    request_get.assert_not_called()
    warning.assert_called_once()


def test_resolve_oidc_issuer_keeps_arm_issuer_when_discovery_is_unreachable(mocked_responses: responses, mocker):
    arm_issuer = "https://issuer.example/cluster"
    mocked_responses.add(
        method=responses.GET,
        url=f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        body=requests.ConnectionError(),
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    warning.assert_called_once()


def test_resolve_oidc_issuer_rejects_oversized_discovery(mocked_responses: responses, mocker):
    arm_issuer = "https://issuer.example/cluster"
    mocked_responses.add(
        method=responses.GET,
        url=f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        body=b"x" * (OIDC_DISCOVERY_MAX_RESPONSE_BYTES + 1),
        status=200,
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    warning.assert_called_once()


def test_resolve_oidc_issuer_ignores_redirects(mocked_responses: responses, mocker):
    arm_issuer = "https://issuer.example/cluster"
    mocked_responses.add(
        method=responses.GET,
        url=f"{arm_issuer}{OIDC_DISCOVERY_PATH}",
        headers={"Location": "https://issuer.example/redirect"},
        status=302,
    )
    warning = mocker.patch("azext_edge.edge.providers.orchestration.resources.instances.logger.warning")

    assert resolve_oidc_issuer(arm_issuer) == arm_issuer
    assert len(mocked_responses.calls) == 1
    warning.assert_called_once()
