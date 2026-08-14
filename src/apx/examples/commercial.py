# SPDX-License-Identifier: MPL-2.0
"""Optional commercial extension proof. Local state, test credit, no ad/payment network."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime,timezone
from uuid import uuid4

from ..personal import Campaign,ContentVariant,Offer,Reward,RewardReceipt
from ..providers import ActionProvider


def build_commercial_reference_provider(*,enabled=True):
    provider=ActionProvider("commercial.reference","Optional Commercial Reference",provenance="native_provider",
        extensions=("content","offers","rewards","campaigns") if enabled else (),metadata={"commercial_optional":True,"enabled":enabled})
    if not enabled: return provider
    variants=(ContentVariant("general",("general",),"General"),ContentVariant("developer",("developer",),"Developer"),ContentVariant("technical",("technical",),"Technical"))
    offer=Offer("gpu-test","commercial.reference","GPU test credit",("developer","gpu"),sponsored=True,compensation={"amount":"0.10","currency":"TEST"},actions=("offer.accept",))
    reward=Reward("reward-test","commercial.reference","test_credit",{"amount":"0.10","currency":"TEST"},offer.id)
    campaign=Campaign("campaign-test","commercial.reference",(offer,),eligibility={"criteria":["developer"]},budget={"amount":"100","currency":"TEST"})
    accepted=set()
    empty={"type":"object","properties":{},"additionalProperties":False}; identified=lambda key:{"type":"object","required":[key],"properties":{key:{"type":"string"}},"additionalProperties":False}
    @provider.action("content.variant.list",input_schema=empty,idempotent=True)
    def content_variants(): return {"variants":[asdict(item) for item in variants]}
    @provider.action("offer.inspect",input_schema=identified("offer_id"),idempotent=True)
    def inspect_offer(offer_id): return asdict(offer) if offer_id==offer.id else {"found":False}
    @provider.action("reward.offer",input_schema=identified("reward_id"),idempotent=True)
    def inspect_reward(reward_id): return asdict(reward) if reward_id==reward.id else {"found":False}
    @provider.action("offer.accept",input_schema=identified("offer_id"),risk="account_change",confirmation="confirm",idempotent=True,retry="idempotency_required")
    def accept_offer(offer_id): accepted.add(offer_id); return {"offer_id":offer_id,"accepted":True}
    @provider.action("reward.claim",input_schema=identified("reward_id"),risk="financial",confirmation="transaction",idempotent=True,retry="idempotency_required")
    def claim_reward(reward_id):
        if offer.id not in accepted: return {"reward_id":reward_id,"status":"denied","reason":"offer not accepted"}
        receipt=RewardReceipt("rr_"+uuid4().hex,reward.id,reward.provider,"completed",reward.value,datetime.now(timezone.utc).isoformat())
        return asdict(receipt)
    @provider.prepare("reward.claim")
    def prepare_claim(reward_id): return {"effect":"Claim test credit","confirmation_terms":{"reward_id":reward_id,"value":reward.value}}
    @provider.action("campaign.inspect",input_schema=identified("campaign_id"),idempotent=True)
    def inspect_campaign(campaign_id): return asdict(campaign) if campaign_id==campaign.id else {"found":False}
    for action_id,status in (("campaign.create","draft"),("campaign.update","draft"),("campaign.pause","paused"),("campaign.publish","published"),("reward.configure","configured")):
        def business_action(_status=status,**values): return {"status":_status,"input":values}
        provider.action(action_id,input_schema={"type":"object"},risk="account_change",confirmation="confirm",idempotent=True)(business_action)
    return provider
