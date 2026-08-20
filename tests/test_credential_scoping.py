import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apx import APX


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n' + extra)
    return path


ROLES_TOML = (
    '[[actors]]\nid="agent:deployer"\nkind="agent"\nroles=["deployer"]\n'
    '[[roles]]\nname="deployer"\nallow=[{action="secret.reveal",scope={id=["cloudflare_token"]}},{action="secret.get"}]\n'
    '[credentials.cloudflare_token]\nsource="environment"\nreference="CF_TOKEN_TEST"\n'
    '[credentials.other_secret]\nsource="environment"\nreference="OTHER_TEST"\n'
)


class CredentialScopingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name), ROLES_TOML), plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_agent_cannot_reveal_raw_credentials_even_with_scope(self):
        with mock.patch.dict("os.environ", {"CF_TOKEN_TEST": "abc123"}):
            denied = self.cloud.run("secret.reveal", actor="agent:deployer", id="cloudflare_token")
        self.assertFalse(denied.ok)
        self.assertEqual(denied.error.code, "permission_denied")
        self.assertNotIn("abc123", str(denied.to_dict()))

    def test_agent_cannot_reveal_a_different_credential(self):
        with mock.patch.dict("os.environ", {"OTHER_TEST": "xyz"}):
            denied = self.cloud.run("secret.reveal", actor="agent:deployer", id="other_secret")
        self.assertFalse(denied.ok)
        self.assertEqual(denied.error.code, "permission_denied")

    def test_scope_check_never_exposes_the_value_on_denial(self):
        with mock.patch.dict("os.environ", {"OTHER_TEST": "should-never-appear"}):
            denied = self.cloud.run("secret.reveal", actor="agent:deployer", id="other_secret")
        self.assertNotIn("should-never-appear", str(denied.to_dict()))

    def test_unscoped_secret_get_metadata_still_works_for_any_credential(self):
        # secret.get (masked metadata only) has no id-scope restriction on this role,
        # confirming the new "id" scope dimension is additive, not a blanket new gate.
        result = self.cloud.run("secret.get", actor="agent:deployer", id="other_secret")
        self.assertTrue(result.ok, result.error)


if __name__ == "__main__":
    unittest.main()
