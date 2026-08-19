# SPDX-License-Identifier: MIT
"""APX: Universal Action Protocol & Capability Fabric."""

from .cloud import APX
from .axp import ActionDefinition, ActionReceipt, ActionRequest, ActionResult, ActorDescriptor, Capability, Connection, Context, CredentialHandle, Event, PreparedAction, Resource, ResourceRelationship, SecretInput, StructuredError, VersionInfo, validate_action_transition
from .providers import ActionProvider, CompatibilityResult, HTTPProviderAdapter, ProviderDiscoveryError, ProviderIdentity, ProviderManifest, RemoteProvider, validate_provider
from .servers import ServerInventory
from .client import APXClient, HTTPClientTransport, LocalClientTransport
from .runtime import OperationAccepted, ProviderPolicyDenied, ProviderSession
from .fabric import ActionComponent, ActionPath, Bridge, CapabilityGraph, ComponentCandidate, ComponentRegistry, CompositionEngine, CompositionStep, audit_component_candidate
from .personal import Campaign, Consent, ContentVariant, ContextEntry, Offer, OpaqueFinancialResource, PersonalContextStore, PersonalizationPolicy, RelevanceRequest, RelevanceResult, Reward, RewardReceipt, build_personal_provider
from .credentials import CredentialReference
from .models import Host, Project
from .conformance import bridge_conformance
from .daily import CalendarResource, FinancialResource, PasswordManager, PasswordManagerResource, SubscriptionObservation, relate_subscription

__all__ = ["ActionComponent","ActionDefinition","ActionPath","ActionProvider","ActionReceipt","ActionRequest","ActionResult","ActorDescriptor","APXClient","Bridge","CalendarResource","Campaign","Consent","Capability","CapabilityGraph","ComponentCandidate","ComponentRegistry","CompositionEngine","CompositionStep","Connection","ContentVariant","Context","ContextEntry","CredentialHandle","CredentialReference","Event","FinancialResource","Host","HTTPClientTransport","HTTPProviderAdapter","APX","LocalClientTransport","Offer","OpaqueFinancialResource","OperationAccepted","PasswordManager","PasswordManagerResource","PersonalContextStore","PersonalizationPolicy","PreparedAction","Project","CompatibilityResult","ProviderDiscoveryError","ProviderIdentity","ProviderManifest","ProviderPolicyDenied","ProviderSession","RemoteProvider","RelevanceRequest","RelevanceResult","Resource","ResourceRelationship","Reward","RewardReceipt","SecretInput","ServerInventory","StructuredError","SubscriptionObservation","VersionInfo","audit_component_candidate","bridge_conformance","build_personal_provider","relate_subscription","validate_action_transition","validate_provider"]
__version__ = "0.8.3"