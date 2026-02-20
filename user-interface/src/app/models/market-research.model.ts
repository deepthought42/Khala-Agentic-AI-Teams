/** Team topology for market research. */
export type TeamTopology = 'unified' | 'split';

/** Request for POST /market-research/run. */
export interface RunMarketResearchRequest {
  product_concept: string;
  target_users: string;
  business_goal: string;
  topology?: TeamTopology;
  transcript_folder_path?: string;
  transcripts?: string[];
  human_approved?: boolean;
  human_feedback?: string;
}

/** Interview insight from research. */
export interface InterviewInsight {
  source: string;
  user_jobs?: string[];
  pain_points?: string[];
  desired_outcomes?: string[];
  direct_quotes?: string[];
}

/** Market signal with confidence. */
export interface MarketSignal {
  signal: string;
  confidence?: number;
  evidence?: string[];
}

/** Viability recommendation. */
export interface ViabilityRecommendation {
  verdict: string;
  confidence?: number;
  rationale?: string[];
  suggested_next_experiments?: string[];
}

/** Response from POST /market-research/run. */
export interface TeamOutput {
  status: string;
  topology: TeamTopology;
  mission_summary: string;
  insights: InterviewInsight[];
  market_signals: MarketSignal[];
  recommendation: ViabilityRecommendation;
  proposed_research_scripts: string[];
  human_feedback?: string;
}
