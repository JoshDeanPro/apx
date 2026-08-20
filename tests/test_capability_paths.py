from pathlib import Path

from apx import APX, Resource
from apx.providers import ActionProvider


def config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n')
    return path


def test_capability_paths_find_configured_provider_resource(tmp_path):
    cloud = APX(config(tmp_path), plugins=False)
    provider = ActionProvider("domains.test", "Domains", metadata={"version": "1"})
    provider.resource(Resource("domain:example.test", "domain", "example.test", capabilities=("domain.list",)))

    @provider.action("domain.list", description="List domains", resource_type="domain", idempotent=True)
    def list_domains():
        return {"domains": ["example.test"]}

    cloud.register_provider(provider)
    result = cloud.run("capability.paths", action="domain.list")

    assert result.ok
    assert result.result["paths"][0]["resource"] == "domain:example.test"
    assert result.result["paths"][0]["provider"] == "domains.test"
