import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apx import APX
from apx.docs import generate


def config(tmp_path: Path) -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('''version=1
[credentials.token]
source="environment"
reference="APX_TEST_TOKEN"
groups=["demo"]

[[hosts]]
name="mac"
transport="local"

[[hosts]]
name="vps"
transport="local"

[[projects]]
name="demo"
description="A demo project."
services=["demo-api"]
domains=["demo.example"]
groups=["demo"]

[[projects.locations]]
host="mac"
path="/path/to/demo"
role="development"

[[projects.locations]]
host="vps"
path="/srv/demo"
role="production"

[projects.context]
architecture=["Single service on the VPS."]
avoid=["Do not add a database without a demonstrated need."]
commands={test="python -m pytest"}
deployment={method="scripts/deploy.sh"}

[[actors]]
id="human:ethan"
roles=["deployer","reader"]

[[roles]]
name="deployer"
[[roles.allow]]
action="service.restart"
scope={project=["demo"]}

[[roles]]
name="reader"
[[roles.allow]]
action="docs.generate"
[[roles.allow]]
action="mission.*"
''')
    return path


class DocsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=APX(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_human_audience_covers_operations(self):
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"super-secret-value"}):
            text=generate(self.cloud,"demo","human")
        self.assertIn("demo-api",text); self.assertIn("demo.example",text)
        self.assertIn("scripts/deploy.sh",text)
        self.assertIn("token",text)  # credential reference name, not the value
        self.assertNotIn("super-secret-value",text)

    def test_ai_audience_lists_allowed_actions_and_production_location(self):
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"super-secret-value"}):
            text=generate(self.cloud,"demo","ai")
        self.assertIn("service.restart",text)
        self.assertIn("vps",text)
        self.assertNotIn("super-secret-value",text)

    def test_machine_audience_is_valid_deterministic_json(self):
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"super-secret-value"}):
            first=generate(self.cloud,"demo","machine")
            second=generate(self.cloud,"demo","machine")
        self.assertEqual(first,second)
        payload=json.loads(first)
        self.assertEqual(payload["project"]["name"],"demo")
        self.assertNotIn("super-secret-value",first)

    def test_machine_audience_includes_related_missions(self):
        result=self.cloud.run("mission.create",actor="human:ethan",project="demo",title="Fix bug",objective="Repair the thing")
        self.assertTrue(result.ok,result.to_dict())
        payload=json.loads(generate(self.cloud,"demo","machine"))
        kinds={r["kind"] for r in payload["resources"]}
        self.assertIn("mission",kinds)

    def test_unknown_project_or_audience_raises(self):
        with self.assertRaises(ValueError): generate(self.cloud,"missing","human")
        with self.assertRaises(ValueError): generate(self.cloud,"demo","printed")

    def test_docs_action_is_shared_across_python_and_cli_path(self):
        result=self.cloud.run("docs.generate",actor="human:ethan",project="demo",audience="machine")
        self.assertTrue(result.ok)
        json.loads(result.result["content"])  # must be valid JSON


if __name__ == "__main__": unittest.main()
