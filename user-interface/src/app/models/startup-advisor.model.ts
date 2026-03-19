import type { AgentInfo } from './studio-grid.model';

export type StartupStage = 'idea' | 'mvp' | 'early-revenue' | 'growth' | 'scale';

export type FocusArea =
  | 'customer_discovery'
  | 'product_strategy'
  | 'growth_gtm'
  | 'fundraising_finance'
  | 'operations_legal'
  | 'founder_coaching';

export interface StartupAdvisorIntake {
  startupName: string;
  founderRole: string;
  stage: StartupStage;
  primaryGoal: string;
  currentChallenge: string;
  targetHorizonWeeks: number;
  teamSize: number;
  budgetBand: string;
  focusAreas: FocusArea[];
}

export interface StartupAdvisorRecommendation {
  agentId: string;
  title: string;
  fitSummary: string;
  confidence: number;
  suggestedOutcomes: string[];
  source: AgentInfo;
}

export interface StartupExecutionMilestone {
  id: string;
  title: string;
  owner: string;
  eta: string;
  successMetric: string;
}

export interface StartupExecutionPlan {
  northStar: string;
  timelineLabel: string;
  milestones: StartupExecutionMilestone[];
  risks: string[];
}
