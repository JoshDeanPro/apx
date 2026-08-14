from __future__ import annotations
from apx.voice_input import FastIntentRouter,IntentInput,PressGesture,TextInputProvider,route_input,voice_health


def test_fast_router_resolves_known_action_without_reasoning():
    result=route_input(TextInputProvider("Check Caddy on the VPS"),FastIntentRouter())
    assert result["route"]=={"status":"resolved","action":"service.status","parameters":{"service":"caddy"},"target":"vps","confidence":.98,"confirmation":"none","reason":None}
    assert result["metrics"]["reasoning_calls"]==0


def test_high_risk_voice_never_executes_directly():
    route=FastIntentRouter().route(IntentInput("voice","Send $500"))
    assert route.status=="prepare_required" and route.confirmation=="transaction"


def test_chat_mode_does_not_route_action():
    assert FastIntentRouter().route(IntentInput("voice","restart caddy on vps",mode="chat")).status=="conversation_required"
    assert PressGesture("F8",100).mode=="chat" and PressGesture("F8",500).mode=="action"


def test_voice_health_is_optional_without_model():
    assert voice_health()["status"]=="available_to_configure"
