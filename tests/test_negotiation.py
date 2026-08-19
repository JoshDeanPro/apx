from __future__ import annotations

import json

import pytest

from apx.axp import ActionDefinition, StructuredError
from apx.http import HTTPFailure
from apx.providers import (
    ProviderDiscoveryError,
    ProviderIdentity,
    ProviderManifest,
    RemoteProvider,
    evaluate_compatibility,
)


def manifest(**kwargs):
    return ProviderManifest(provider=ProviderIdentity("test", "Test"), actions=(), **kwargs)


def test_compatibility_retains_reasons_and_exposes_structured_errors():
    result = evaluate_compatibility(
        {"capabilities": (), "permissions": (), "authentication": (), "actor_type": "agent"},
        manifest(required_capabilities=("files.read",), required_permissions=("read",),
                 required_credentials=("api",), allowed_actor_types=("human",)),
    )

    assert not result.compatible
    assert any("required capability missing" in reason for reason in result.reasons)
    assert {error.code for error in result.errors} == {"incompatible_requirements"}
    assert all(isinstance(error, StructuredError) for error in result.errors)
    assert all(error.details["kind"] in {"capability", "permission", "credential", "actor"} for error in result.errors)


def test_protocol_mismatch_is_structured_and_non_retryable():
    result = evaluate_compatibility(
        {"apx_version": "9.9"},
        manifest(apx_version="0.1", compatibility=("0.1",)),
    )

    assert not result.compatible
    assert result.errors[0].code == "protocol_version_unsupported"
    assert result.errors[0].retryable is False


def test_incompatible_discovery_raises_value_error_compatible_structured_error():
    payload = json.dumps(manifest(required_capabilities=("magic",)).to_dict()).encode()

    class Response:
        def read(self, _limit):
            return payload

    with pytest.raises(ProviderDiscoveryError) as caught:
        RemoteProvider.discover("https://provider.example", opener=lambda request, timeout: Response(),
                                client_context={"capabilities": ()})

    assert isinstance(caught.value, ValueError)
    assert caught.value.structured_error.code == "incompatible_requirements"
    assert caught.value.structured_error.retryable is False


def test_discovery_rejects_non_tls_remote_endpoint_structurally():
    with pytest.raises(ProviderDiscoveryError) as caught:
        RemoteProvider.discover("http://provider.example")

    assert caught.value.structured_error.code == "connection_rejected"
    assert caught.value.structured_error.retryable is False


def test_discovery_maps_transport_failure_to_retryable_provider_unavailable():
    def fail(*_args, **_kwargs):
        raise HTTPFailure("timed out", code="timeout")

    with pytest.raises(ProviderDiscoveryError) as caught:
        RemoteProvider.discover("https://provider.example", opener=fail)

    assert caught.value.structured_error.code == "provider_unavailable"
    assert caught.value.structured_error.retryable is True
