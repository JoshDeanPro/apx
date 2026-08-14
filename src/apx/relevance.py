"""Local APX relevance boundary. Commercial data never enters Action/AI context."""
from __future__ import annotations
from dataclasses import asdict
from typing import Any

from .personal import ContentVariant,Offer,PersonalContextStore


class LocalRelevanceEngine:
    def __init__(self,store: PersonalContextStore): self.store=store
    def select_content(self,variants: tuple[ContentVariant,...]) -> dict[str,Any]|None:
        if not variants: return None
        selected=self.store.select_variant(variants)
        variant=selected["variant"] if selected else next((item for item in variants if item.id=="general"),variants[0])
        return {"variant":asdict(variant),"selected_locally":True,"profile_disclosed":{},"personalized":selected is not None}
    def evaluate_offer(self,offer: Offer):
        result=self.store.match_offer(offer)
        return {**result,"offer_id":offer.id,"provider":offer.provider,"presentation_surface":"commercial_only","ai_context":False,"tool_result":False}


def assert_commercial_isolation(value: dict[str,Any]) -> None:
    if value.get("ai_context") or value.get("tool_result"): raise ValueError("commercial content must remain outside AI/Action context")
