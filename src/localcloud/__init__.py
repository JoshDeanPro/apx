"""LOCALCLOUD: use the computers and services you already own together."""

from .cloud import LocalCloud
from .axp import ActionDefinition, ActionRequest, ActionResult, Capability, Context, Event, Resource, StructuredError
from .models import Host, Project

__all__ = ["ActionDefinition","ActionRequest","ActionResult","Capability","Context","Event","Host","LocalCloud","Project","Resource","StructuredError"]
__version__ = "0.2.0"
