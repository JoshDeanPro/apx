# SPDX-License-Identifier: MIT
"""Built-in Blueprints. Small on purpose -- composable primitives, not giant
combination templates. `project/documented` demonstrates composition by including
`project/base-layout` rather than redeclaring its steps."""
from __future__ import annotations

from .blueprints import Blueprint, BlueprintStep

_README_TEMPLATE = "# {project_name}\n\nManaged by APX Blueprints (project/base-layout).\n"
_ARCHITECTURE_TEMPLATE = "# Architecture\n\n_Populate this file as {project_name} takes shape._\n"

BASE_LAYOUT = Blueprint(
    stable_id="bp_1000000000001",
    name="project/base-layout",
    version="1.0.0",
    description="Ensure a project's baseline directory structure and README exist.",
    category="project",
    tags=("filesystem", "scaffold"),
    aliases=("base-layout", "project-base"),
    inputs={
        "path": {"type": "path", "required": True, "description": "Filesystem root of the project"},
        "project_name": {"type": "string", "required": False, "default": ""},
    },
    resulting_capabilities=("project.structure.base",),
    steps=(
        BlueprintStep("src_dir", "directory.ensure", {"path": "{path}/src"}),
        BlueprintStep("docs_dir", "directory.ensure", {"path": "{path}/docs"}),
        BlueprintStep("readme", "file.template.ensure", {"path": "{path}/README.md", "content": _README_TEMPLATE}, after=("src_dir", "docs_dir")),
    ),
)

DOCUMENTED = Blueprint(
    stable_id="bp_1000000000002",
    name="project/documented",
    version="1.0.0",
    description="A base-layout project that also carries an architecture-notes stub.",
    category="project",
    tags=("filesystem", "scaffold", "docs"),
    aliases=("documented-project",),
    includes=("project/base-layout",),
    resulting_capabilities=("project.docs.architecture_stub",),
    steps=(
        BlueprintStep("architecture_stub", "file.template.ensure", {"path": "{path}/docs/ARCHITECTURE.md", "content": _ARCHITECTURE_TEMPLATE}),
    ),
)

BUILT_IN_BLUEPRINTS: tuple[Blueprint, ...] = (BASE_LAYOUT, DOCUMENTED)
