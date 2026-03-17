from unittest.mock import patch

from branding_team import (
    BrandingMission,
    BrandingTeamOrchestrator,
    BrandPhase,
    HumanReview,
    WorkflowStatus,
)
from branding_team.models import BrandCheckRequest, CompetitiveSnapshot


def _mission() -> BrandingMission:
    return BrandingMission(
        company_name="Northstar Labs",
        company_description="A strategic studio helping product teams ship cohesive digital experiences",
        target_audience="enterprise product leaders",
        values=["clarity", "trust", "momentum"],
        differentiators=["hands-on partnership", "execution speed"],
    )


def test_requires_human_approval() -> None:
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(
        mission=_mission(), human_review=HumanReview(approved=False, feedback="Need legal review.")
    )

    assert result.status == WorkflowStatus.NEEDS_HUMAN_DECISION
    assert result.human_feedback == "Need legal review."
    assert result.mood_boards
    assert result.wiki_backlog
    # Phase-specific outputs should be populated
    assert result.strategic_core is not None
    assert result.narrative_messaging is not None
    assert result.visual_identity is not None
    assert result.channel_activation is not None
    assert result.governance is not None
    assert result.phase_gates


def test_ready_for_rollout_with_brand_checks() -> None:
    orchestrator = BrandingTeamOrchestrator()
    checks = [
        BrandCheckRequest(
            asset_name="Homepage refresh",
            asset_description="Clear messaging for enterprise product leaders with trust-building proof points",
        ),
        BrandCheckRequest(
            asset_name="Flashy ad",
            asset_description="Guaranteed viral growth for everyone overnight",
        ),
    ]

    result = orchestrator.run(
        mission=_mission(), human_review=HumanReview(approved=True), brand_checks=checks
    )

    assert result.status == WorkflowStatus.READY_FOR_ROLLOUT
    assert len(result.brand_guidelines) >= 4
    assert result.design_system.foundation_tokens
    assert len(result.brand_checks) == 2
    assert any(not item.is_on_brand for item in result.brand_checks)
    # Phase outputs
    assert result.current_phase == BrandPhase.COMPLETE
    assert result.strategic_core is not None
    assert result.strategic_core.positioning_statement
    assert result.strategic_core.core_values
    assert result.narrative_messaging is not None
    assert result.narrative_messaging.tagline
    assert result.visual_identity is not None
    assert result.visual_identity.color_palette
    assert result.channel_activation is not None
    assert result.channel_activation.channel_guidelines
    assert result.governance is not None
    assert result.governance.brand_health_kpis


def test_run_with_include_market_research_adds_competitive_snapshot() -> None:
    with patch("branding_team.adapters.market_research.request_market_research") as mock_mr:
        mock_mr.return_value = CompetitiveSnapshot(
            summary="Competitive summary",
            similar_brands=["A", "B"],
            insights=["insight1"],
            source="market_research_team",
        )
        orchestrator = BrandingTeamOrchestrator()
        result = orchestrator.run(
            mission=_mission(),
            human_review=HumanReview(approved=True),
            include_market_research=True,
        )
        assert result.competitive_snapshot is not None
        assert result.competitive_snapshot.summary == "Competitive summary"
        assert result.competitive_snapshot.source == "market_research_team"


def test_run_with_include_design_assets_adds_design_asset_result() -> None:
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(
        mission=_mission(),
        human_review=HumanReview(approved=True),
        include_design_assets=True,
    )
    assert result.design_asset_result is not None
    assert result.design_asset_result.request_id.startswith("design_")
    assert result.design_asset_result.status == "pending"


def test_run_with_brand_id_and_store_appends_version() -> None:
    from branding_team.store import BrandingStore

    store = BrandingStore()
    client = store.create_client("Test Client")
    mission = BrandingMission(
        company_name="Northstar Labs",
        company_description="A strategic studio helping product teams ship cohesive digital experiences",
        target_audience="enterprise product leaders",
        values=["clarity", "trust"],
        differentiators=["speed"],
    )
    brand = store.create_brand(client.id, mission)
    assert brand is not None
    assert brand.version == 0
    orchestrator = BrandingTeamOrchestrator()
    orchestrator.run(
        mission=mission,
        human_review=HumanReview(approved=True),
        store=store,
        client_id=client.id,
        brand_id=brand.id,
    )
    updated = store.get_brand(client.id, brand.id)
    assert updated is not None
    assert updated.version == 1
    assert updated.latest_output is not None
    assert len(updated.history) == 1


def test_run_phase_stops_at_strategic_core() -> None:
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run_phase(
        mission=_mission(),
        phase=BrandPhase.STRATEGIC_CORE,
        human_review=HumanReview(approved=True),
    )
    assert result.strategic_core is not None
    assert result.narrative_messaging is None
    assert result.visual_identity is None
    assert result.channel_activation is None
    assert result.governance is None
    assert result.current_phase == BrandPhase.STRATEGIC_CORE
    # Partial run must NOT signal rollout readiness even when approved
    assert result.status == WorkflowStatus.NEEDS_HUMAN_DECISION


def test_approved_partial_run_is_not_rollout_ready() -> None:
    """Approved intermediate phases must not be marked READY_FOR_ROLLOUT."""
    orchestrator = BrandingTeamOrchestrator()
    for phase in (
        BrandPhase.STRATEGIC_CORE,
        BrandPhase.NARRATIVE_MESSAGING,
        BrandPhase.VISUAL_IDENTITY,
        BrandPhase.CHANNEL_ACTIVATION,
    ):
        result = orchestrator.run_phase(
            mission=_mission(),
            phase=phase,
            human_review=HumanReview(approved=True),
        )
        assert result.status == WorkflowStatus.NEEDS_HUMAN_DECISION, (
            f"Phase {phase.value} with approved=True should not be READY_FOR_ROLLOUT"
        )
        assert result.current_phase != BrandPhase.COMPLETE


def test_run_phase_stops_at_narrative_messaging() -> None:
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run_phase(
        mission=_mission(),
        phase=BrandPhase.NARRATIVE_MESSAGING,
        human_review=HumanReview(approved=False),
    )
    assert result.strategic_core is not None
    assert result.narrative_messaging is not None
    assert result.visual_identity is None
    assert result.channel_activation is None
    assert result.governance is None
    assert result.current_phase == BrandPhase.NARRATIVE_MESSAGING
    assert result.status == WorkflowStatus.NEEDS_HUMAN_DECISION


def test_full_run_produces_all_phase_outputs() -> None:
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(mission=_mission(), human_review=HumanReview(approved=True))

    assert result.strategic_core is not None
    assert result.narrative_messaging is not None
    assert result.visual_identity is not None
    assert result.channel_activation is not None
    assert result.governance is not None
    assert result.current_phase == BrandPhase.COMPLETE
    assert result.brand_book is not None
    assert result.brand_book.content
    assert "Brand Purpose" in result.brand_book.content
    assert "Brand Story" in result.brand_book.content
    assert "Color Palette" in result.brand_book.content


def test_phase_gates_are_populated() -> None:
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(mission=_mission(), human_review=HumanReview(approved=True))
    assert len(result.phase_gates) == 5
    for gate in result.phase_gates:
        assert gate.status.value in ("approved", "not_started", "pending_review", "in_progress")


def test_strategic_core_output_detail() -> None:
    """Verify Phase 1 output has the expected depth and detail."""
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(mission=_mission(), human_review=HumanReview(approved=True))
    sc = result.strategic_core
    assert sc is not None
    assert sc.brand_purpose
    assert sc.mission_statement
    assert sc.vision_statement
    assert sc.positioning_statement
    assert sc.brand_promise
    assert len(sc.core_values) == 3  # clarity, trust, momentum
    for cv in sc.core_values:
        assert cv.value
        assert cv.behavioral_definition
        assert cv.observable_behaviors
    assert sc.target_audience_segments
    assert sc.differentiation_pillars
    assert sc.brand_discovery.strengths
    assert sc.brand_discovery.weaknesses


def test_narrative_messaging_output_detail() -> None:
    """Verify Phase 2 output has full verbal identity components."""
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(mission=_mission(), human_review=HumanReview(approved=True))
    nm = result.narrative_messaging
    assert nm is not None
    assert nm.brand_story
    assert nm.hero_narrative
    assert nm.tagline
    assert nm.tagline_rationale
    assert nm.brand_archetypes
    assert nm.messaging_framework
    assert nm.audience_message_maps
    assert nm.elevator_pitches
    assert len(nm.elevator_pitches) >= 3
    assert nm.boilerplate_variants
    assert nm.persona_profiles


def test_visual_identity_output_detail() -> None:
    """Verify Phase 3 output has complete design system."""
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(mission=_mission(), human_review=HumanReview(approved=True))
    vi = result.visual_identity
    assert vi is not None
    assert vi.logo_suite
    assert vi.color_palette
    for color in vi.color_palette:
        assert color.hex_value
        assert color.psychological_rationale
    assert vi.typography_system
    assert vi.iconography_style
    assert vi.photography_direction
    assert vi.motion_principles
    assert vi.voice_tone_spectrum
    assert vi.language_dos
    assert vi.language_donts
    assert vi.digital_adaptations


def test_channel_activation_output_detail() -> None:
    """Verify Phase 4 output has activation playbook."""
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(mission=_mission(), human_review=HumanReview(approved=True))
    ca = result.channel_activation
    assert ca is not None
    assert ca.brand_experience_principles
    assert ca.signature_moments
    assert ca.channel_guidelines
    assert len(ca.channel_guidelines) >= 4
    assert ca.brand_architecture
    assert ca.naming_conventions
    assert ca.terminology_glossary
    assert ca.brand_in_action


def test_governance_output_detail() -> None:
    """Verify Phase 5 output has operational governance."""
    orchestrator = BrandingTeamOrchestrator()
    result = orchestrator.run(mission=_mission(), human_review=HumanReview(approved=True))
    gov = result.governance
    assert gov is not None
    assert gov.ownership_model
    assert gov.decision_authority
    assert gov.approval_workflows
    assert gov.agency_briefing_protocols
    assert gov.asset_management_guidance
    assert gov.training_onboarding_plan
    assert gov.brand_health_kpis
    assert gov.tracking_methodology
    assert gov.review_trigger_points
    assert gov.evolution_framework
    assert gov.version_control_cadence
