from apx import ContentVariant,Offer,PersonalContextStore,PersonalizationPolicy
from apx.relevance import LocalRelevanceEngine,assert_commercial_isolation


def test_content_selected_locally_without_profile_disclosure(tmp_path):
    store=PersonalContextStore(tmp_path/"context.json"); store.add("technology","developer technical")
    result=LocalRelevanceEngine(store).select_content((ContentVariant("general",("general",),"General"),ContentVariant("technical",("technical",),"Technical")))
    assert result["variant"]["id"]=="technical" and result["profile_disclosed"]=={}


def test_disabled_personalization_selects_generic(tmp_path):
    store=PersonalContextStore(tmp_path/"context.json",PersonalizationPolicy(enabled=False)); store.add("technology","technical")
    result=LocalRelevanceEngine(store).select_content((ContentVariant("general",(),"General"),ContentVariant("technical",("technical",),"Technical")))
    assert result["variant"]["id"]=="general" and not result["personalized"]


def test_sponsored_offer_isolated_from_ai_and_respects_opt_in(tmp_path):
    store=PersonalContextStore(tmp_path/"context.json",PersonalizationPolicy(commercial_content="none")); store.add("technology","gpu")
    result=LocalRelevanceEngine(store).evaluate_offer(Offer("offer","provider","GPU",("gpu",),sponsored=True))
    assert not result["relevant"] and result["presentation_surface"]=="commercial_only"
    assert_commercial_isolation(result)


def test_minimum_reward_and_blocked_categories_are_enforced_locally(tmp_path):
    policy=PersonalizationPolicy(commercial_content="compensated_only",allowed_providers=("provider",),allowed_commercial_categories=("gpu",),blocked_commercial_categories=("gambling",),minimum_compensation={"amount":"0.05","currency":"TEST"})
    store=PersonalContextStore(tmp_path/"context.json",policy); store.add("technology","gpu")
    engine=LocalRelevanceEngine(store)
    low=engine.evaluate_offer(Offer("low","provider","Low",("gpu",),sponsored=True,compensation={"amount":"0.01","currency":"TEST"}))
    blocked=engine.evaluate_offer(Offer("blocked","provider","Blocked",("gpu","gambling"),sponsored=True,compensation={"amount":"1.00","currency":"TEST"}))
    enough=engine.evaluate_offer(Offer("enough","provider","Enough",("gpu",),sponsored=True,compensation={"amount":"0.10","currency":"TEST"}))
    assert not low["relevant"] and low["reason"]=="minimum compensation not met"
    assert not blocked["relevant"] and blocked["reason"]=="category blocked"
    assert enough["relevant"]
