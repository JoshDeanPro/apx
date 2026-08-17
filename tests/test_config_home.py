# SPDX-License-Identifier: MIT
"""Installed APX and source APX are separate things: the runtime's config and its
state overlays live under APX_HOME, never in whatever directory you happen to be
standing in, and never inside a source checkout."""
from __future__ import annotations

import json

import pytest

from apx.config import apx_home, default_config_path, is_source_checkout, migrate_into_home, state_files


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    monkeypatch.delenv("APX_CONFIG", raising=False)
    monkeypatch.delenv("APX_HOME", raising=False)


def test_home_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("APX_HOME", str(tmp_path/"elsewhere"))
    assert apx_home() == tmp_path/"elsewhere"
    assert default_config_path() == tmp_path/"elsewhere"/"config.toml"


def test_working_directory_is_never_the_config(monkeypatch, tmp_path):
    """The regression this whole split exists for: a checkout you cd into must not
    silently become the machine's configuration."""
    monkeypatch.setenv("APX_HOME", str(tmp_path/"home"))
    (tmp_path/"checkout").mkdir()
    (tmp_path/"checkout"/"apx.toml").write_text("version = 1\n")
    monkeypatch.chdir(tmp_path/"checkout")
    assert default_config_path() == tmp_path/"home"/"config.toml"


def test_explicit_config_still_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("APX_HOME", str(tmp_path/"home"))
    monkeypatch.setenv("APX_CONFIG", str(tmp_path/"project.toml"))
    assert default_config_path() == tmp_path/"project.toml"


def test_source_checkout_is_recognised(tmp_path):
    checkout = tmp_path/"apx"
    (checkout/".git").mkdir(parents=True)
    (checkout/"src"/"apx").mkdir(parents=True)
    (checkout/"pyproject.toml").write_text("")
    assert is_source_checkout(checkout/"apx.toml")
    plain = tmp_path/"config"
    plain.mkdir()
    assert not is_source_checkout(plain/"config.toml")


def test_migration_moves_config_and_every_state_overlay(monkeypatch, tmp_path):
    monkeypatch.setenv("APX_HOME", str(tmp_path/"home"))
    checkout = tmp_path/"checkout"
    checkout.mkdir()
    source = checkout/"apx.toml"
    source.write_text("version = 1\n")
    (checkout/"apx.missions.json").write_text(json.dumps({"missions": []}))
    (checkout/"apx.grants.json").write_text(json.dumps({"grants": []}))
    (checkout/"apx.missions.json.lock").write_text("")

    outcome = migrate_into_home(source)

    assert outcome["migrated"]
    assert outcome["config"] == str(tmp_path/"home"/"config.toml")
    assert (tmp_path/"home"/"config.toml").read_text() == "version = 1\n"
    assert (tmp_path/"home"/"config.missions.json").exists()
    assert (tmp_path/"home"/"config.grants.json").exists()
    assert (tmp_path/"home"/"config.missions.json.lock").exists()
    assert not source.exists()
    assert not (checkout/"apx.missions.json").exists()


def test_migration_refuses_to_overwrite_an_existing_installation(monkeypatch, tmp_path):
    monkeypatch.setenv("APX_HOME", str(tmp_path/"home"))
    (tmp_path/"home").mkdir()
    (tmp_path/"home"/"config.toml").write_text("version = 1\n")
    source = tmp_path/"apx.toml"
    source.write_text("version = 1\n")
    with pytest.raises(FileExistsError):
        migrate_into_home(source)
    assert source.exists()


def test_migration_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("APX_HOME", str(tmp_path/"home"))
    (tmp_path/"home").mkdir()
    installed = tmp_path/"home"/"config.toml"
    installed.write_text("version = 1\n")
    assert migrate_into_home(installed)["migrated"] is False


def test_state_files_are_derived_from_the_config_name(tmp_path):
    names = {path.name for path in state_files(tmp_path/"config.toml")}
    assert "config.missions.json" in names and "config.grants.json" in names
