import pytest
from apx.axp import ActionDefinition, ActionRequirements, PreparedAction, Connection
from apx.providers import ProviderManifest, ProviderIdentity, evaluate_compatibility, CompatibilityResult
from apx.credentials import CredentialRegistry, SecretsManager, CredentialReference, CredentialError

def test_status_lifecycle_transitions():
    from apx.axp import ActionResult
    import dataclasses
    
    action = ActionResult(action="test.action", request_id="req1", target={}, status="pending", ok=True)
    assert action.status == "pending"
    
    # Valid transitions
    action = dataclasses.replace(action, status="in-progress")
    assert action.status == "in-progress"
    
    action = dataclasses.replace(action, status="completed")
    assert action.status == "completed"

def test_connection_capability_evaluation():
    # Prove incompatibility rejections work
    server_manifest = ProviderManifest(
        provider=ProviderIdentity(id="test-provider", name="Test Provider"),
        actions=(),
        required_capabilities=("magic",),
        required_permissions=("admin",),
        allowed_actor_types=("human",)
    )
    
    # Missing capability and permission
    client_context_1 = {"capabilities": (), "permissions": (), "actor_type": "human"}
    res1 = evaluate_compatibility(client_context_1, server_manifest)
    assert not res1.compatible
    assert any("required capability missing: magic" in r for r in res1.reasons)
    assert any("permission unavailable: admin" in r for r in res1.reasons)
    
    # Invalid actor type
    client_context_2 = {"capabilities": ("magic",), "permissions": ("admin",), "actor_type": "agent"}
    res2 = evaluate_compatibility(client_context_2, server_manifest)
    assert not res2.compatible
    assert any("actor type incompatible: agent" in r for r in res2.reasons)
    
    # All satisfied
    client_context_3 = {"capabilities": ("magic",), "permissions": ("admin",), "actor_type": "human"}
    res3 = evaluate_compatibility(client_context_3, server_manifest)
    assert res3.compatible

def test_credential_scoping():
    # Prove a mismatched scope correctly denies access
    refs = {
        "db-password": CredentialReference(id="db-password", source="environment", reference="DB_PASSWORD", scopes=("database", "admin")),
    }
    registry = CredentialRegistry(refs)
    secrets = SecretsManager(registry)
    
    # Mock environment variable
    import os
    os.environ["DB_PASSWORD"] = "secret123"
    
    try:
        # Access without scope should work if caller doesn't provide one? Wait, no, if the caller provides an incompatible scope
        # Wait, if `caller_scope` is provided and it's not in the allowed scopes, it should fail
        with pytest.raises(CredentialError) as exc:
            secrets.reveal("db-password", caller_scope="web-server")
        
        assert exc.value.code == "credential_scope_mismatch"
        assert exc.value.details["required_scope"] == "web-server"
        
        # Access with valid scope
        val = secrets.reveal("db-password", caller_scope="database")
        assert val["value"] == "secret123"
        
    finally:
        del os.environ["DB_PASSWORD"]
