import { Injectable, signal } from '@angular/core';
import { map, tap } from 'rxjs/operators';
import { Observable, of } from 'rxjs';
import { StudioGridApiService } from './studio-grid-api.service';
import type {
  AgentInfo,
  FindAgentsRequest,
  FocusArea,
  StartupAdvisorIntake,
  StartupAdvisorRecommendation,
  StartupExecutionPlan,
} from '../models';

const FOCUS_AREA_LABELS: Record<FocusArea, string> = {
  customer_discovery: 'Customer discovery and user interviews',
  product_strategy: 'Product strategy and roadmap sequencing',
  growth_gtm: 'Growth and go-to-market execution',
  fundraising_finance: 'Fundraising narrative and financial planning',
  operations_legal: 'Operations, legal, and company setup',
  founder_coaching: 'Founder coaching and decision cadence',
};

const STARTUP_AGENT_HINTS = [
  'startup',
  'founder',
  'customer_discovery',
  'product_strategy',
  'growth_gtm',
  'fundraising_finance',
  'operations_legal',
  'founder_coach',
] as const;

@Injectable({ providedIn: 'root' })
export class StartupAdvisorFacadeService {
  private readonly intakeSignal = signal<StartupAdvisorIntake | null>(null);
  private readonly recommendationsSignal = signal<StartupAdvisorRecommendation[]>([]);

  constructor(private readonly studioGridApi: StudioGridApiService) {}

  get intakeSnapshot(): StartupAdvisorIntake | null {
    return this.intakeSignal();
  }

  get recommendationsSnapshot(): StartupAdvisorRecommendation[] {
    return this.recommendationsSignal();
  }

  setIntake(intake: StartupAdvisorIntake): void {
    this.intakeSignal.set(intake);
  }

  loadStartupCatalog(): Observable<AgentInfo[]> {
    return this.studioGridApi.listAgents().pipe(
      map((response) => response.agents.filter((agent) => this.looksStartupRelevant(agent)))
    );
  }

  getRecommendations(intake: StartupAdvisorIntake, forceRefresh = false): Observable<StartupAdvisorRecommendation[]> {
    if (!forceRefresh && this.recommendationsSignal().length > 0 && this.intakeSignal()?.startupName === intake.startupName) {
      return of(this.recommendationsSignal());
    }

    this.intakeSignal.set(intake);
    const request = this.buildFindRequest(intake);
    return this.studioGridApi.findAgents(request).pipe(
      map((response) => response.assisting_agents.map((agent, index) => this.toRecommendation(agent, intake, index))),
      tap((recommendations) => this.recommendationsSignal.set(recommendations))
    );
  }

  buildExecutionPlan(): StartupExecutionPlan | null {
    const intake = this.intakeSignal();
    const recommendations = this.recommendationsSignal();
    if (!intake || recommendations.length === 0) {
      return null;
    }

    const keyAdvisors = recommendations.slice(0, 3).map((item) => item.title);
    return {
      northStar: intake.primaryGoal,
      timelineLabel: `${intake.targetHorizonWeeks}-week execution arc`,
      milestones: [
        {
          id: 'm1',
          title: 'Validate problem and define ICP',
          owner: keyAdvisors[0] ?? 'Customer Discovery Advisor',
          eta: 'Week 1-2',
          successMetric: '15 qualified interviews and clear pain-score trends',
        },
        {
          id: 'm2',
          title: 'Prioritize roadmap and test offer',
          owner: keyAdvisors[1] ?? 'Product Strategy Advisor',
          eta: 'Week 3-5',
          successMetric: 'One validated offer with conversion baseline',
        },
        {
          id: 'm3',
          title: 'Scale execution with operating cadence',
          owner: keyAdvisors[2] ?? 'Growth GTM Advisor',
          eta: `Week 6-${intake.targetHorizonWeeks}`,
          successMetric: 'Weekly KPI review and documented owner accountability',
        },
      ],
      risks: [
        'Founder bandwidth constraints may delay customer feedback loops.',
        'Go-to-market assumptions may require additional channel tests.',
        'Financial runway risk if conversion milestones are not achieved on schedule.',
      ],
    };
  }

  private buildFindRequest(intake: StartupAdvisorIntake): FindAgentsRequest {
    const skills = intake.focusAreas.map((area) => FOCUS_AREA_LABELS[area]);
    return {
      problem: [
        `Startup: ${intake.startupName}`,
        `Stage: ${intake.stage}`,
        `Founder role: ${intake.founderRole}`,
        `Primary goal: ${intake.primaryGoal}`,
        `Current challenge: ${intake.currentChallenge}`,
      ].join(' | '),
      skills,
      limit: 6,
    };
  }

  private toRecommendation(agent: AgentInfo, intake: StartupAdvisorIntake, index: number): StartupAdvisorRecommendation {
    const rawId = agent.agent_id ?? 'startup_advisor';
    const confidence = Math.max(72, 95 - (index * 6));
    return {
      agentId: rawId,
      title: this.toTitle(rawId),
      fitSummary: `Aligned to ${intake.stage} stage priorities with emphasis on "${intake.primaryGoal}".`,
      confidence,
      suggestedOutcomes: [
        'Clarify decisions to unblock weekly execution.',
        'Set measurable outcomes for the next planning cycle.',
        'Create an advisor-led accountability rhythm.',
      ],
      source: agent,
    };
  }

  private looksStartupRelevant(agent: AgentInfo): boolean {
    const bag = [
      agent.agent_id,
      ...(agent.keywords ?? []),
      ...(agent.skills ?? []),
      ...(agent.actions ?? []),
    ]
      .join(' ')
      .toLowerCase();
    return STARTUP_AGENT_HINTS.some((hint) => bag.includes(hint));
  }

  private toTitle(agentId: string): string {
    return agentId
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }
}
