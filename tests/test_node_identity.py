# SPDX-License-Identifier: MPL-2.0
"""One fleet topology, copied to every node; exactly one line of it is machine
specific. Getting that line wrong is not a cosmetic problem -- it makes a node run
another machine's `local` commands and report the answers under that machine's
name, which is how a copied config looks configured and is silently lying."""
from __future__ import annotations

import pytest

from apx.config import explain_self_host, load
from apx.transports import LocalTransport, SSHTransport, TransportError, transport_for, transports_for

FLEET = """
version = 1

[[hosts]]
name = "mac"
transport = "local"

[[hosts]]
name = "home"
transport = "ssh"
target = "home-eth"

[[hosts]]
name = "vps"
transport = "ssh"
target = "vps"
"""


@pytest.fixture(autouse=True)
def _no_node_override(monkeypatch):
    monkeypatch.delenv("APX_NODE", raising=False)


def _config(tmp_path, extra=""):
    path = tmp_path/"config.toml"
    path.write_text(FLEET + extra)
    return path


def test_declared_node_wins_over_the_local_marker(tmp_path):
    hosts, _ = load(_config(tmp_path, '\n[node]\nname = "vps"\n'))
    assert hosts["vps"].is_self and hosts["vps"].transport == "local"
    assert not hosts["mac"].is_self


def test_the_other_machines_local_entry_is_not_runnable_here(tmp_path):
    """The actual bug: on `home`, "mac" is declared local. It must not execute here."""
    hosts, _ = load(_config(tmp_path, '\n[node]\nname = "home"\n'))
    assert transports_for(hosts["mac"]) == []
    with pytest.raises(TransportError, match="declared local on another machine"):
        transport_for(hosts["mac"])


def test_the_self_host_runs_locally_even_when_declared_over_ssh(tmp_path):
    hosts, _ = load(_config(tmp_path, '\n[node]\nname = "home"\n'))
    assert isinstance(transport_for(hosts["home"]), LocalTransport)
    assert hosts["home"].target is None


def test_other_hosts_keep_their_declared_transport(tmp_path):
    hosts, _ = load(_config(tmp_path, '\n[node]\nname = "home"\n'))
    assert isinstance(transport_for(hosts["vps"]), SSHTransport)
    assert hosts["vps"].target == "vps"


def test_environment_override(tmp_path, monkeypatch):
    monkeypatch.setenv("APX_NODE", "vps")
    hosts, _ = load(_config(tmp_path))
    assert hosts["vps"].is_self


def test_an_unknown_node_name_is_an_error_not_a_silent_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("APX_NODE", "laptop")
    with pytest.raises(ValueError, match="not one of the configured hosts"):
        load(_config(tmp_path))


RAW = {"hosts": [{"name": "mac", "transport": "local"},
                 {"name": "home", "transport": "ssh", "target": "root@home-eth"},
                 {"name": "vps", "transport": "ssh", "target": "vps"}]}
TARGETS = {"mac": None, "home": "root@home-eth", "vps": "vps"}


def test_hostname_matching_a_host_name_identifies_this_machine(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "vps")
    outcome = explain_self_host(RAW, list(TARGETS), TARGETS)
    assert outcome == {"name": "vps", "method": "hostname", "confident": True, "hostname": "vps"}


def test_hostname_matching_an_ssh_target_identifies_this_machine(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "home-eth")
    outcome = explain_self_host(RAW, list(TARGETS), TARGETS)
    assert outcome["name"] == "home" and outcome["method"] == "ssh_target" and outcome["confident"]


def test_the_declared_local_guess_is_reported_as_unconfident(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "some-unrelated-box")
    outcome = explain_self_host(RAW, list(TARGETS), TARGETS)
    # Nothing identifies this machine, so the only answer left is a guess -- and on
    # a copied config that guess names the machine the config came from.
    assert outcome["name"] == "mac"
    assert outcome["method"] == "declared_local_fallback"
    assert outcome["confident"] is False
