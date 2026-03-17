"""Agent implementations for the 5-phase branding strategy framework.

Phase 1 — Strategic Core: Brand Strategist
Phase 2 — Narrative & Messaging: Brand Narrative Architect
Phase 3 — Visual & Expressive Identity: Visual Identity Director
Phase 4 — Experience & Channel Activation: Channel Activation Strategist
Phase 5 — Governance & Evolution: Brand Governance Lead

Legacy agents (BrandComplianceAgent) are retained for brand-check functionality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .models import (
    ApprovalWorkflow,
    AudienceMessageMap,
    AudienceSegment,
    BrandArchetype,
    BrandArchitectureRule,
    BrandCheckRequest,
    BrandCheckResult,
    # Legacy models still used for backward-compat bridge
    BrandCodification,
    BrandDiscoveryAudit,
    BrandHealthKPI,
    BrandInActionExample,
    BrandingMission,
    ChannelActivationOutput,
    ChannelGuideline,
    ColorEntry,
    CoreValue,
    CreativeRefinementPlan,
    DesignSystemDefinition,
    DifferentiationPillar,
    ElevatorPitch,
    GovernanceOutput,
    LogoUsageRule,
    MessagingPillar,
    MoodBoardConcept,
    NarrativeMessagingOutput,
    PersonaProfile,
    StrategicCoreOutput,
    TypographySpec,
    VisualIdentityOutput,
    VoiceToneEntry,
    WikiEntry,
    WritingGuidelines,
)

# ===================================================================
# Phase 1 — Strategic Core
# ===================================================================


@dataclass
class StrategicCoreAgent:
    """Defines the strategic foundation: purpose, positioning, values, audience, and differentiation."""

    role: str = "Brand Strategist"

    def execute(self, mission: BrandingMission) -> StrategicCoreOutput:
        values = mission.values or ["trust", "clarity", "momentum"]
        differentiators = mission.differentiators or ["domain expertise", "execution speed"]

        core_values = [
            CoreValue(
                value=v,
                behavioral_definition=f"We demonstrate '{v}' in every customer interaction and internal decision.",
                observable_behaviors=[
                    f"Team members cite '{v}' when explaining trade-off decisions",
                    f"Customer feedback explicitly references experiences aligned with '{v}'",
                    f"Internal reviews evaluate work against the '{v}' standard",
                ],
            )
            for v in values[:5]
        ]

        audience_segments = [
            AudienceSegment(
                name=mission.target_audience,
                description=f"Primary buyers and users of {mission.company_name}'s offerings.",
                pain_points=[
                    "Inconsistent brand experiences across touchpoints",
                    "Difficulty articulating differentiation to their own stakeholders",
                    "Over-reliance on ad-hoc creative decisions",
                ],
                goals=[
                    "Ship a cohesive brand experience across all channels",
                    "Build lasting trust with their own customers",
                    "Reduce time-to-market for brand-aligned assets",
                ],
                decision_drivers=[
                    "Proven methodology and track record",
                    "Speed of execution without sacrificing quality",
                    "Depth of strategic thinking behind recommendations",
                ],
            ),
        ]

        diff_pillars = [
            DifferentiationPillar(
                pillar=d,
                proof_points=[
                    f"Demonstrated {d.lower()} through measurable client outcomes",
                    f"Case studies showing {d.lower()} as a decisive factor",
                ],
                competitive_context=f"Most competitors lack {d.lower()} as a core capability.",
            )
            for d in differentiators[:4]
        ]

        return StrategicCoreOutput(
            brand_discovery=BrandDiscoveryAudit(
                current_brand_perception=(
                    f"{mission.company_name} is currently perceived as a capable player "
                    f"in {mission.company_description.lower().rstrip('.')}."
                ),
                market_position="Emerging challenger with strong domain credibility.",
                strengths=[d for d in differentiators[:3]],
                weaknesses=[
                    "Limited brand awareness outside core audience",
                    "No formal brand governance",
                ],
                opportunities=[
                    "Codify brand to unlock scalable marketing",
                    "Differentiate through consistent brand experience",
                ],
                threats=[
                    "Competitors investing heavily in brand",
                    "Market commoditization without clear positioning",
                ],
                stakeholder_insights=[
                    "Internal team alignment on values is strong but undocumented",
                    "Customers value the relationship but can't articulate why we're different",
                ],
            ),
            brand_purpose=(
                f"{mission.company_name} exists to help {mission.target_audience} "
                f"achieve transformative outcomes through {mission.company_description.lower().rstrip('.')}."
            ),
            mission_statement=(
                f"To empower {mission.target_audience} by turning "
                f"{mission.company_description.lower().rstrip('.')} into consistent, recognizable experiences "
                f"that build trust and drive results."
            ),
            vision_statement=(
                f"A world where every interaction with {mission.company_name} feels cohesive, intentional, "
                f"and unmistakably aligned to our promise."
            ),
            core_values=core_values,
            brand_promise=(
                "Every customer touchpoint will feel cohesive, useful, and unmistakably aligned "
                "to one unified brand system."
            ),
            positioning_statement=(
                f"For {mission.target_audience} who need "
                f"{mission.company_description.lower().rstrip('.')}, "
                f"{mission.company_name} is the {differentiators[0].lower() if differentiators else 'partner'} "
                f"that delivers {values[0].lower() if values else 'trust'} "
                f"because {differentiators[-1].lower() if len(differentiators) > 1 else 'we execute with discipline'}."
            ),
            target_audience_segments=audience_segments,
            differentiation_pillars=diff_pillars,
        )


# ===================================================================
# Phase 2 — Narrative & Messaging
# ===================================================================


@dataclass
class NarrativeMessagingAgent:
    """Builds the verbal identity: story, archetypes, tagline, messaging framework, and personas."""

    role: str = "Brand Narrative Architect"

    def execute(
        self, mission: BrandingMission, strategic_core: StrategicCoreOutput
    ) -> NarrativeMessagingOutput:
        values = [cv.value for cv in strategic_core.core_values] or ["trust", "clarity"]
        primary_audience = mission.target_audience

        brand_archetypes = [
            BrandArchetype(
                archetype="The Sage",
                rationale=(
                    f"Rooted in {mission.company_name}'s commitment to {values[0]} and strategic depth. "
                    f"The Sage archetype communicates wisdom, expertise, and informed guidance."
                ),
                personality_traits=["knowledgeable", "trustworthy", "analytical", "clear-headed"],
            ),
            BrandArchetype(
                archetype="The Creator",
                rationale=(
                    "Reflects the company's drive to build cohesive, intentional brand experiences "
                    "from the ground up — craftsmanship as a core identity trait."
                ),
                personality_traits=["inventive", "detail-oriented", "visionary", "quality-focused"],
            ),
        ]

        messaging_pillars = [
            MessagingPillar(
                pillar=dp.pillar,
                key_message=f"We deliver {dp.pillar.lower()} that {primary_audience} can measure and trust.",
                proof_points=dp.proof_points,
            )
            for dp in strategic_core.differentiation_pillars
        ]

        audience_maps = [
            AudienceMessageMap(
                audience_segment=seg.name,
                primary_message=(
                    f"{mission.company_name} helps {seg.name} achieve {seg.goals[0].lower() if seg.goals else 'their goals'} "
                    f"through {strategic_core.differentiation_pillars[0].pillar.lower() if strategic_core.differentiation_pillars else 'proven expertise'}."
                ),
                supporting_messages=[
                    f"Built on {values[0]} — not just promises, but measurable outcomes.",
                    f"Trusted by {primary_audience} who demand rigor and results.",
                ],
                tone_adjustments=f"Lead with outcomes for {seg.name}; use proof points early.",
            )
            for seg in strategic_core.target_audience_segments
        ]

        personas = [
            PersonaProfile(
                name=f"Primary: {seg.name}",
                role=seg.description,
                demographics=f"Decision-makers in {primary_audience} organizations.",
                psychographics=(
                    "Values substance over flash. Skeptical of marketing hype. "
                    "Responds to data, proof, and demonstrated expertise."
                ),
                goals=seg.goals,
                frustrations=seg.pain_points,
                media_habits=[
                    "Industry publications and thought leadership",
                    "Peer recommendations and case studies",
                    "LinkedIn and professional communities",
                ],
                jobs_to_be_done=[
                    f"Establish a brand that {primary_audience} trusts instinctively",
                    "Reduce brand inconsistency across teams and channels",
                    "Accelerate go-to-market with brand-aligned assets",
                ],
            )
            for seg in strategic_core.target_audience_segments
        ]

        return NarrativeMessagingOutput(
            brand_story=(
                f"{mission.company_name} was founded on a simple belief: {primary_audience} deserve "
                f"better than fragmented brand experiences. Through {mission.company_description.lower().rstrip('.')}, "
                f"we turn strategic intent into cohesive reality."
            ),
            hero_narrative=(
                f"You're a leader in {primary_audience}. You know your product is excellent — but your brand "
                f"doesn't yet tell that story consistently. {mission.company_name} becomes your strategic partner, "
                f"giving you the brand system that lets every touchpoint reinforce why you're the right choice."
            ),
            brand_archetypes=brand_archetypes,
            tagline=f"{values[0].capitalize()}. Built to last." if values else "Built to last.",
            tagline_rationale=(
                f"Anchors the brand in its primary value ({values[0]}) while signaling durability and commitment. "
                f"Works across marketing, product, and employer brand contexts."
            ),
            messaging_framework=messaging_pillars,
            audience_message_maps=audience_maps,
            elevator_pitches=[
                ElevatorPitch(
                    tier="5-second",
                    pitch=f"{mission.company_name}: {values[0]} for {primary_audience}.",
                ),
                ElevatorPitch(
                    tier="30-second",
                    pitch=(
                        f"{mission.company_name} helps {primary_audience} build brand experiences that are "
                        f"cohesive, measurable, and aligned to a unified strategy."
                    ),
                ),
                ElevatorPitch(
                    tier="2-minute",
                    pitch=(
                        f"{mission.company_name} is a strategic brand partner for {primary_audience}. "
                        f"We combine {', '.join(values[:3])} with a rigorous 5-phase methodology that takes "
                        f"brands from strategic foundation through full market activation. Our clients don't "
                        f"just get a logo — they get a complete brand system that every team member can "
                        f"execute independently."
                    ),
                ),
            ],
            boilerplate_variants=[
                (
                    f"{mission.company_name} is a brand strategy partner for {primary_audience}, "
                    f"specializing in {mission.company_description.lower().rstrip('.')}. "
                    f"Founded on {values[0] if values else 'trust'}, we deliver brand systems that "
                    f"scale with our clients."
                ),
                (
                    f"At {mission.company_name}, we believe {primary_audience} deserve brand experiences "
                    f"as rigorous as their products. We make that happen."
                ),
            ],
            persona_profiles=personas,
        )


# ===================================================================
# Phase 3 — Visual & Expressive Identity
# ===================================================================


@dataclass
class VisualIdentityAgent:
    """Defines the visual and expressive identity system: logo, color, type, voice, and tone."""

    role: str = "Visual Identity Director"

    def execute(
        self,
        mission: BrandingMission,
        strategic_core: StrategicCoreOutput,
        narrative: NarrativeMessagingOutput,
    ) -> VisualIdentityOutput:
        values = [cv.value for cv in strategic_core.core_values] or ["trust", "clarity"]
        primary_value = values[0] if values else "trust"

        return VisualIdentityOutput(
            logo_suite=[
                LogoUsageRule(
                    variant="primary",
                    usage_context="Default usage on light backgrounds; marketing materials, website header.",
                    minimum_size="24px height",
                    clear_space="1x logo height on all sides",
                ),
                LogoUsageRule(
                    variant="reversed",
                    usage_context="Dark backgrounds; photo overlays.",
                    minimum_size="24px height",
                    clear_space="1x logo height on all sides",
                ),
                LogoUsageRule(
                    variant="icon-only",
                    usage_context="Favicons, app icons, social avatars, constrained spaces.",
                    minimum_size="16px",
                    clear_space="0.5x icon width on all sides",
                ),
                LogoUsageRule(
                    variant="monochrome",
                    usage_context="Single-color contexts: print, embroidery, watermarks.",
                    minimum_size="24px height",
                    clear_space="1x logo height on all sides",
                ),
            ],
            color_palette=[
                ColorEntry(
                    name="Primary Deep",
                    hex_value="#1A2B4A",
                    usage="Primary backgrounds, headers, key CTAs",
                    psychological_rationale=(
                        f"Deep navy communicates depth, stability, and {primary_value} — "
                        f"anchoring the brand's strategic authority."
                    ),
                ),
                ColorEntry(
                    name="Accent Bright",
                    hex_value="#00B4D8",
                    usage="CTAs, highlights, interactive elements, data emphasis",
                    psychological_rationale=(
                        "Electric cyan signals innovation and forward momentum without "
                        "sacrificing professionalism."
                    ),
                ),
                ColorEntry(
                    name="Neutral Stone",
                    hex_value="#E8E4DF",
                    usage="Backgrounds, cards, content areas, breathing room",
                    psychological_rationale=(
                        "Warm neutral provides visual rest and approachability, "
                        "balancing the authority of the primary palette."
                    ),
                ),
                ColorEntry(
                    name="Surface White",
                    hex_value="#FAFAF8",
                    usage="Content surfaces, text backgrounds, clean layouts",
                    psychological_rationale="Near-white surface maintains readability and modern aesthetic.",
                ),
                ColorEntry(
                    name="Critical Red",
                    hex_value="#E63946",
                    usage="Errors, destructive actions, urgent alerts only",
                    psychological_rationale="Reserved for true alerts to preserve signal clarity.",
                ),
                ColorEntry(
                    name="Success Green",
                    hex_value="#2A9D8F",
                    usage="Confirmations, success states, positive metrics",
                    psychological_rationale="Teal-green signals growth and positive outcomes.",
                ),
            ],
            typography_system=[
                TypographySpec(
                    role="display",
                    font_family="Inter or equivalent geometric sans-serif",
                    weight_range="600–800",
                    usage_notes="Headlines, hero sections, major callouts. Tight tracking.",
                ),
                TypographySpec(
                    role="body",
                    font_family="Inter or equivalent geometric sans-serif",
                    weight_range="400–500",
                    usage_notes="All body copy. 16px base, 1.5 line-height for readability.",
                ),
                TypographySpec(
                    role="caption",
                    font_family="Inter or equivalent geometric sans-serif",
                    weight_range="400",
                    usage_notes="Labels, metadata, helper text. 12–14px, slightly increased tracking.",
                ),
                TypographySpec(
                    role="monospace",
                    font_family="JetBrains Mono or equivalent",
                    weight_range="400–500",
                    usage_notes="Code samples, technical content, data tables.",
                ),
            ],
            iconography_style=(
                "Line-based icons with 2px stroke weight, rounded caps. "
                "Consistent 24px grid. Functional clarity over decoration."
            ),
            illustration_style=(
                "Minimal, geometric illustrations using brand colors. "
                "Flat with subtle depth through overlapping shapes. "
                "Used to explain concepts, not for decoration."
            ),
            photography_direction=(
                "Documentary-style photography: real people in real contexts. "
                "Natural lighting, candid moments, professional but not sterile. "
                "Focus on collaboration, outcomes, and craft."
            ),
            video_direction=(
                "Clean transitions, steady camera, natural pacing. "
                "Talking-head thought leadership and product walkthroughs. "
                "Avoid stock footage and over-produced effects."
            ),
            motion_principles=[
                "Subtle and purposeful — animation communicates state changes, not decoration",
                "Duration: 150–300ms for micro-interactions, 400–600ms for transitions",
                "Easing: ease-out for entrances, ease-in for exits",
                "Respect prefers-reduced-motion for accessibility",
            ],
            data_visualization_style=(
                "Use brand palette with semantic color mapping. "
                "Lead with insight, not decoration. "
                "Label directly on chart when possible; minimize legends."
            ),
            digital_adaptations=[
                "Favicon: icon-only logo variant at 32x32 and 16x16",
                "App icon: icon-only variant with primary-deep background, 1024x1024 master",
                "OG image template: 1200x630, brand-deep background, white wordmark, tagline",
                "Email header: 600px wide, primary wordmark on surface-white",
            ],
            voice_tone_spectrum=[
                VoiceToneEntry(
                    context="marketing",
                    tone="Confident and clear. Lead with outcomes. Aspirational but grounded in proof.",
                    examples=[
                        "Your brand should work as hard as your product.",
                        "We don't guess — we build on strategy.",
                    ],
                ),
                VoiceToneEntry(
                    context="product / UX",
                    tone="Direct, helpful, concise. Guide without lecturing.",
                    examples=[
                        "Brand check complete. 2 items need attention.",
                        "Your positioning statement has been updated.",
                    ],
                ),
                VoiceToneEntry(
                    context="support",
                    tone="Empathetic and solution-oriented. Acknowledge, then resolve.",
                    examples=[
                        "We hear you — let's get this sorted.",
                        "Here's what happened, and here's how we'll fix it.",
                    ],
                ),
                VoiceToneEntry(
                    context="internal / employer",
                    tone="Transparent, collaborative, candid. Treat colleagues like adults.",
                    examples=[
                        "Here's the trade-off and why we chose this path.",
                        "We're behind on this — here's the plan to catch up.",
                    ],
                ),
            ],
            language_dos=[
                f"Use a {mission.desired_voice} voice across all channels",
                "Lead with customer outcomes before product features",
                "Prefer plain language over jargon",
                "Use active voice and direct calls to action",
                "Ground claims in proof points and examples",
                "Keep paragraphs short and scannable",
            ],
            language_donts=[
                "Do not overpromise or use unverifiable superlatives",
                "Avoid inconsistent terminology for core offerings",
                "Do not bury the key value proposition",
                "Avoid passive constructions that dilute authority",
                "Do not use more than one exclamation mark per asset",
                "Avoid buzzwords without substantive meaning",
            ],
        )


# ===================================================================
# Phase 4 — Experience & Channel Activation
# ===================================================================


@dataclass
class ChannelActivationAgent:
    """Defines how the brand shows up across every channel and touchpoint."""

    role: str = "Channel Activation Strategist"

    def execute(
        self,
        mission: BrandingMission,
        strategic_core: StrategicCoreOutput,
        narrative: NarrativeMessagingOutput,
        visual_identity: VisualIdentityOutput,
    ) -> ChannelActivationOutput:
        return ChannelActivationOutput(
            brand_experience_principles=[
                "Every touchpoint should feel intentional, not accidental",
                "Consistency builds trust — deviations erode it exponentially",
                "The brand speaks with one voice, adapted for context but never contradicting itself",
                "Experiences should reduce cognitive load — make the next action obvious",
                "Surprise and delight within the brand system, not outside it",
            ],
            signature_moments=[
                "First interaction: the onboarding experience should feel like a guided strategy session",
                "Deliverable handoff: every document and artifact should be unmistakably on-brand",
                "Milestone celebration: mark project milestones with branded rituals (e.g., strategy-lock email)",
                "Annual brand review: a structured retrospective with the client",
            ],
            sensory_elements=[
                f"Visual: {visual_identity.color_palette[0].name if visual_identity.color_palette else 'brand'} palette as anchor",
                "Sonic: no current audio brand — explore subtle UI sounds aligned with motion principles",
                "Haptic: premium paper stock for physical deliverables, embossed covers",
                "Spatial: consistent meeting room branding for in-person workshops",
            ],
            channel_guidelines=[
                ChannelGuideline(
                    channel="website",
                    strategy="Primary conversion and credibility engine. Lead with outcomes and proof.",
                    dos=[
                        "Use hero sections with clear value propositions",
                        "Include social proof above the fold",
                        "Maintain brand typography and color system",
                        "Provide clear navigation with minimal cognitive load",
                    ],
                    donts=[
                        "Don't use stock photography of generic business scenes",
                        "Don't bury case studies — surface them prominently",
                        "Don't deviate from the approved color palette",
                    ],
                    content_types=["landing pages", "case studies", "blog posts", "product pages"],
                    frequency_guidance="Major content refresh quarterly; blog cadence biweekly.",
                ),
                ChannelGuideline(
                    channel="social media",
                    strategy="Thought leadership and community building. Human voice, professional insights.",
                    dos=[
                        "Share insights and lessons, not just promotions",
                        "Use brand visuals and templates consistently",
                        "Engage authentically in comments and discussions",
                    ],
                    donts=[
                        "Don't use trending memes that conflict with brand personality",
                        "Don't post without visual brand alignment",
                        "Don't auto-post identical content across platforms",
                    ],
                    content_types=[
                        "thought leadership",
                        "client highlights",
                        "team culture",
                        "industry commentary",
                    ],
                    frequency_guidance="LinkedIn: 3-4x/week. Twitter: daily. Instagram: 2-3x/week.",
                ),
                ChannelGuideline(
                    channel="email",
                    strategy="Relationship nurturing and conversion. Personalized, valuable, concise.",
                    dos=[
                        "Use branded email templates with consistent header/footer",
                        "Personalize subject lines and content",
                        "Include one clear CTA per email",
                    ],
                    donts=[
                        "Don't send emails without brand-compliant formatting",
                        "Don't overload with multiple CTAs",
                        "Don't use ALL CAPS in subject lines",
                    ],
                    content_types=[
                        "newsletters",
                        "drip campaigns",
                        "transactional",
                        "event invitations",
                    ],
                    frequency_guidance="Newsletter: biweekly. Drip: event-triggered.",
                ),
                ChannelGuideline(
                    channel="events and presentations",
                    strategy="High-impact brand moments. Consistent deck templates, speaker talking points.",
                    dos=[
                        "Use the branded presentation template",
                        "Open with the positioning statement or a relevant elevator pitch",
                        "Leave attendees with branded takeaways",
                    ],
                    donts=[
                        "Don't freestyle slides without the template",
                        "Don't present data without brand-aligned visualization",
                    ],
                    content_types=["keynotes", "workshops", "webinars", "trade show booths"],
                    frequency_guidance="As needed — every external presentation must be brand-reviewed.",
                ),
                ChannelGuideline(
                    channel="partner and co-marketing",
                    strategy="Protect brand integrity in shared contexts. Clear co-branding rules.",
                    dos=[
                        "Use co-branding guidelines for logo placement and hierarchy",
                        "Maintain brand voice even in joint materials",
                    ],
                    donts=[
                        "Don't allow partners to modify brand assets",
                        "Don't subordinate brand identity in joint materials without approval",
                    ],
                    content_types=[
                        "co-branded landing pages",
                        "joint case studies",
                        "partner directories",
                    ],
                    frequency_guidance="Per partnership agreement.",
                ),
                ChannelGuideline(
                    channel="internal communications",
                    strategy="Consistent internal brand reinforcement. Employees are brand ambassadors.",
                    dos=[
                        "Use internal templates for all-hands, memos, and updates",
                        "Reinforce brand values in internal communications",
                        "Make brand assets easily accessible to all team members",
                    ],
                    donts=[
                        "Don't treat internal comms as brand-exempt",
                        "Don't use off-brand templates for internal documents",
                    ],
                    content_types=[
                        "all-hands decks",
                        "internal newsletters",
                        "onboarding materials",
                        "Slack/Teams",
                    ],
                    frequency_guidance="All-hands: monthly. Internal newsletter: biweekly.",
                ),
            ],
            brand_architecture=[
                BrandArchitectureRule(
                    entity="parent brand",
                    relationship=f"{mission.company_name} is the master brand; all products exist under it.",
                    naming_convention="[Company Name] + [Product Name] — e.g., 'Northstar Studio'",
                    visual_treatment="Full logo suite; primary color palette.",
                ),
                BrandArchitectureRule(
                    entity="sub-brand / product",
                    relationship="Products are endorsed by the parent brand, not independent.",
                    naming_convention="[Company Name] [Product] — no independent logos without approval.",
                    visual_treatment="Parent logo + product name in secondary type. Same color system.",
                ),
            ],
            naming_conventions=[
                "Product names: one or two words, evocative, easy to pronounce globally",
                "Feature names: descriptive, lowercase, no trademarked symbols unless registered",
                "Campaign names: tied to a messaging pillar; reviewed by brand team before launch",
            ],
            terminology_glossary={
                "brand system": "The complete set of strategic, verbal, visual, and experiential brand elements.",
                "brand check": "A structured review to verify an asset is on-brand before publication.",
                "positioning statement": "The concise declaration of who we serve, what we do, and why we're different.",
                "narrative pillar": "A core theme that anchors all brand storytelling.",
                "brand promise": "The singular commitment the brand makes to every customer.",
            },
            brand_in_action=[
                BrandInActionExample(
                    context="Homepage hero section",
                    correct_example=(
                        "Clean layout with positioning statement, proof point, and single CTA "
                        "on brand-deep background with accent highlights."
                    ),
                    incorrect_example=(
                        "Cluttered hero with multiple CTAs, stock photography, "
                        "and copy that doesn't reference the positioning."
                    ),
                    rationale="First impression must reinforce positioning and reduce decision friction.",
                ),
                BrandInActionExample(
                    context="Social media post",
                    correct_example=(
                        "Insight-led post with branded template, link to depth content, "
                        "written in brand voice."
                    ),
                    incorrect_example=(
                        "Promotional post with off-brand visuals, hashtag spam, "
                        "and copy that doesn't match voice guidelines."
                    ),
                    rationale="Social is the highest-frequency brand touchpoint — consistency is critical.",
                ),
                BrandInActionExample(
                    context="Client-facing document",
                    correct_example=(
                        "Branded template with company logo, consistent typography, "
                        "professional layout, and clear section hierarchy."
                    ),
                    incorrect_example=(
                        "Unbranded Word doc with inconsistent fonts, no logo, "
                        "and informal language."
                    ),
                    rationale="Every deliverable is a brand moment. Off-brand documents erode trust.",
                ),
            ],
        )


# ===================================================================
# Phase 5 — Governance & Evolution
# ===================================================================


@dataclass
class GovernanceAgent:
    """Defines how the brand is sustained, measured, and evolved over time."""

    role: str = "Brand Governance Lead"

    def execute(
        self, mission: BrandingMission, strategic_core: StrategicCoreOutput
    ) -> GovernanceOutput:
        return GovernanceOutput(
            ownership_model=(
                "Brand is owned cross-functionally: Strategy owns positioning and messaging; "
                "Design owns visual identity and design system; Marketing owns channel activation; "
                "Executive sponsor holds veto on strategic pivots."
            ),
            decision_authority={
                "strategic pivot": "Executive sponsor + Brand Strategy lead (Phase 1 re-entry)",
                "messaging update": "Brand Strategy lead + Content lead",
                "visual identity change": "Design lead + Brand Strategy lead",
                "channel-specific adaptation": "Channel owner + Design review",
                "new product naming": "Brand Strategy lead + Product lead + Legal",
                "campaign launch": "Channel owner + Brand review approval",
            },
            approval_workflows=[
                ApprovalWorkflow(
                    asset_type="marketing campaign",
                    approvers=["Channel owner", "Brand Strategy lead", "Design review"],
                    sla="5 business days",
                    escalation_path="If no response in SLA → auto-escalate to executive sponsor.",
                ),
                ApprovalWorkflow(
                    asset_type="product naming",
                    approvers=["Brand Strategy lead", "Product lead", "Legal"],
                    sla="10 business days",
                    escalation_path="Legal must sign off before any public usage.",
                ),
                ApprovalWorkflow(
                    asset_type="partner co-branding",
                    approvers=["Brand Strategy lead", "Partnerships", "Design review"],
                    sla="7 business days",
                    escalation_path="No partner materials go live without brand approval.",
                ),
                ApprovalWorkflow(
                    asset_type="social media content",
                    approvers=["Social lead", "Content review (spot-check)"],
                    sla="1 business day",
                    escalation_path="Escalate controversial topics to Brand Strategy lead.",
                ),
            ],
            agency_briefing_protocols=[
                "All agency briefs must include: positioning statement, messaging pillars, voice guidelines, visual identity spec",
                "Agencies receive read-only access to the brand system — no modification rights",
                "Every agency deliverable is reviewed against brand compliance checklist before acceptance",
                "Annual agency alignment workshop to recalibrate on brand direction",
            ],
            asset_management_guidance=[
                "All brand assets stored in a single source-of-truth system (e.g., Brandfolder, Frontify)",
                "Assets tagged by: type, channel, phase, approval status, version",
                "Deprecated assets are archived, not deleted — maintain audit trail",
                "Quarterly asset audit to remove outdated materials from active use",
            ],
            training_onboarding_plan=[
                "New hire brand onboarding: 30-minute session in first week covering strategy, voice, and visual identity",
                "Quarterly brand refresher for all customer-facing teams",
                "Self-serve brand toolkit accessible from internal portal with templates and guidelines",
                "Brand champion program: one person per team responsible for brand consistency",
            ],
            brand_health_kpis=[
                BrandHealthKPI(
                    metric="Brand awareness (aided)",
                    measurement_method="Annual brand tracking survey",
                    target="Increase 10% year-over-year",
                    review_frequency="annually",
                ),
                BrandHealthKPI(
                    metric="Brand consistency score",
                    measurement_method="Quarterly audit of 20 random assets across channels",
                    target="≥90% compliance with brand guidelines",
                    review_frequency="quarterly",
                ),
                BrandHealthKPI(
                    metric="Net Promoter Score (brand-attributed)",
                    measurement_method="Post-interaction NPS survey",
                    target="≥50",
                    review_frequency="quarterly",
                ),
                BrandHealthKPI(
                    metric="Employee brand comprehension",
                    measurement_method="Internal quiz / survey",
                    target="≥80% can articulate positioning and values",
                    review_frequency="semi-annually",
                ),
            ],
            tracking_methodology=(
                "Blend of quantitative (surveys, analytics, compliance audits) and qualitative "
                "(stakeholder interviews, social listening, customer feedback analysis). "
                "Dashboard updated quarterly with trend analysis."
            ),
            review_trigger_points=[
                "Major product launch or pivot",
                "M&A activity (acquiring or being acquired)",
                "Competitive landscape shift that threatens positioning",
                "Brand health KPIs trending negative for two consecutive quarters",
                "Leadership transition at executive level",
                "Market expansion into new geography or vertical",
            ],
            evolution_framework=(
                "Evolution (not revolution) is the default. Brand refreshes update visual and verbal "
                "execution while preserving strategic core. A full rebrand (revolution) requires: "
                "(1) documented failure of current positioning, (2) executive sponsor approval, "
                "(3) full Phase 1 restart. The decision framework: if the strategic core is still "
                "valid, evolve the expression. If the strategic core is broken, restart from Phase 1."
            ),
            version_control_cadence=(
                "Brand system versioned with semantic versioning: major.minor.patch. "
                "Major: strategic pivot or rebrand. Minor: new channel, updated messaging. "
                "Patch: typo fixes, asset updates. Review cycle: quarterly minor review, "
                "annual major review."
            ),
        )


# ===================================================================
# Brand compliance (retained from original)
# ===================================================================


@dataclass
class BrandComplianceAgent:
    """Fields requests to determine whether assets are on brand."""

    role: str = "Brand Compliance Reviewer"

    def evaluate(
        self, checks: List[BrandCheckRequest], mission: BrandingMission
    ) -> List[BrandCheckResult]:
        keywords = [
            *mission.values,
            *mission.differentiators,
            mission.company_name,
            mission.target_audience,
        ]
        lowered_keywords = [k.lower() for k in keywords if k]
        results: List[BrandCheckResult] = []

        for check in checks:
            text = f"{check.asset_name} {check.asset_description}".lower()
            matched = [k for k in lowered_keywords if k in text]
            is_on_brand = len(matched) >= 2
            confidence = min(0.95, 0.45 + (0.1 * len(matched)))

            rationale = [
                "Asset aligns with declared audience and brand language."
                if is_on_brand
                else "Asset is missing core brand signals.",
                f"Detected brand cues: {', '.join(matched[:4]) or 'none'}.",
            ]
            revision_suggestions = []
            if not is_on_brand:
                revision_suggestions = [
                    "Add clearer reference to target audience and expected outcome.",
                    "Use approved voice-and-tone language from the writing playbook.",
                    "Map copy to one narrative pillar and include proof.",
                ]

            results.append(
                BrandCheckResult(
                    asset_name=check.asset_name,
                    is_on_brand=is_on_brand,
                    confidence=round(confidence, 2),
                    rationale=rationale,
                    revision_suggestions=revision_suggestions,
                )
            )

        return results


# ===================================================================
# Legacy bridge agents — adapt new phase agents into old interface
# ===================================================================


@dataclass
class BrandCodificationAgent:
    """Legacy adapter: derives BrandCodification from StrategicCoreOutput."""

    role: str = "Brand Strategist"

    def codify(self, mission: BrandingMission) -> BrandCodification:
        agent = StrategicCoreAgent()
        core = agent.execute(mission)
        return BrandCodification(
            positioning_statement=core.positioning_statement,
            brand_promise=core.brand_promise,
            brand_personality_traits=[cv.value for cv in core.core_values[:4]],
            narrative_pillars=[dp.pillar for dp in core.differentiation_pillars],
        )


@dataclass
class MoodBoardIdeationAgent:
    """Creates candidate brand-image mood boards (legacy interface)."""

    role: str = "Brand Visual Ideation Lead"

    def ideate(self, mission: BrandingMission) -> List[MoodBoardConcept]:
        return [
            MoodBoardConcept(
                title="Modern Confidence",
                visual_direction="Clean grids, product-in-context photography, generous whitespace",
                color_story=["midnight blue", "electric cyan", "neutral stone"],
                typography_direction="Geometric sans-serif with high readability",
                image_style=["documentary-style people", "interface closeups", "subtle gradients"],
            ),
            MoodBoardConcept(
                title="Human Craft",
                visual_direction="Editorial layouts with warm contrast and tactile textures",
                color_story=["charcoal", "terracotta", "cream"],
                typography_direction="Humanist sans-serif paired with a restrained serif",
                image_style=[
                    "team collaboration scenes",
                    "sketch-to-product narratives",
                    "macro textures",
                ],
            ),
        ]


@dataclass
class CreativeRefinementAgent:
    """Facilitates iterative creative refinement and decision making (legacy interface)."""

    role: str = "Creative Director"

    def build_plan(self) -> CreativeRefinementPlan:
        return CreativeRefinementPlan(
            phases=[
                "Diverge: review 2-3 mood boards and map them to audience perception goals",
                "Converge: pick one primary direction and one fallback",
                "Stress-test: apply direction to landing page, sales deck, and social post",
                "Finalize: lock visual and narrative system in v1.0 brand standards",
            ],
            workshop_prompts=[
                "What should prospects feel in the first 5 seconds?",
                "Which direction best communicates credibility and momentum?",
                "What elements are unique enough to own long-term?",
            ],
            decision_criteria=[
                "Audience resonance",
                "Distinctiveness vs competitors",
                "Cross-channel consistency",
                "Execution feasibility in 90 days",
            ],
        )


@dataclass
class BrandGuidelinesAgent:
    """Defines writing, brand, and design-system guidelines (legacy interface)."""

    role: str = "Brand Systems Architect"

    def writing_guidelines(self, mission: BrandingMission) -> WritingGuidelines:
        return WritingGuidelines(
            voice_principles=[
                f"Use a {mission.desired_voice} voice across channels",
                "Lead with customer outcomes before product features",
                "Prefer plain language over jargon",
            ],
            style_dos=[
                "Use active voice and direct calls to action",
                "Ground claims in proof points and examples",
                "Keep paragraphs short and scannable",
            ],
            style_donts=[
                "Do not overpromise or use unverifiable superlatives",
                "Avoid inconsistent terminology for core offerings",
                "Do not bury the key value proposition",
            ],
            editorial_quality_bar=[
                "Every artifact must map to one narrative pillar",
                "Every external asset receives tone and terminology QA",
                "Every major launch includes a message hierarchy",
            ],
        )

    def brand_guidelines(self, codification: BrandCodification) -> List[str]:
        return [
            f"Positioning: {codification.positioning_statement}",
            f"Promise: {codification.brand_promise}",
            "Identity system: logo spacing, color usage, and typography rules are mandatory.",
            "Messaging hierarchy: promise -> pillar -> proof -> CTA.",
            "Governance: route major campaign concepts through brand review before launch.",
        ]

    def design_system(self) -> DesignSystemDefinition:
        return DesignSystemDefinition(
            design_principles=[
                "Clarity over decoration",
                "Consistency at scale",
                "Accessible by default",
            ],
            foundation_tokens=[
                "Color tokens: primary/secondary/surface/critical",
                "Type tokens: display/body/caption scales",
                "Spacing tokens: 4-point base scale",
                "Motion tokens: subtle and meaningful",
            ],
            component_standards=[
                "Buttons: size variants, icon rules, and disabled states",
                "Cards: elevation, border, and content density options",
                "Navigation: desktop and mobile behavior patterns",
            ],
        )


@dataclass
class BrandWikiAgent:
    """Builds and maintains an enterprise-ready brand wiki backlog (legacy interface)."""

    role: str = "Knowledge Systems Manager"

    def build_wiki_backlog(self, mission: BrandingMission) -> List[WikiEntry]:
        return [
            WikiEntry(
                title="Brand North Star",
                summary="Single source of truth for positioning, promise, and narrative pillars.",
                owners=["Brand Strategy", "Executive Sponsor"],
                update_cadence="quarterly",
            ),
            WikiEntry(
                title="Voice & Writing Playbook",
                summary="Examples, approved terminology, and do/don't patterns for all writers.",
                owners=["Content Design", "Comms"],
                update_cadence="monthly",
            ),
            WikiEntry(
                title="Design System & UI Guidance",
                summary="Token catalog, component rules, and accessibility requirements.",
                owners=["Design Systems", "Frontend Platform"],
                update_cadence="monthly",
            ),
            WikiEntry(
                title="Brand Review Intake",
                summary=(
                    "Request template and SLA for checking whether campaigns, pages, and artifacts "
                    "are on brand."
                ),
                owners=["Brand Operations"],
                update_cadence="bi-weekly",
            ),
        ]
