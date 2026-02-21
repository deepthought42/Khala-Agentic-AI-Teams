/** Audience details for targeting content. */
export interface AudienceDetails {
  skill_level?: string;
  profession?: string;
  hobbies?: string[];
  other?: string;
}

/** Request for POST /research-and-review. */
export interface ResearchAndReviewRequest {
  brief: string;
  title_concept?: string;
  audience?: AudienceDetails | string;
  tone_or_purpose?: string;
  max_results?: number;
}

/** A title choice with probability of success. */
export interface TitleChoiceResponse {
  title: string;
  probability_of_success: number;
}

/** Response from POST /research-and-review. */
export interface ResearchAndReviewResponse {
  title_choices: TitleChoiceResponse[];
  outline: string;
  compiled_document?: string;
  notes?: string;
}

/** Request for POST /full-pipeline. */
export interface FullPipelineRequest {
  brief: string;
  title_concept?: string;
  audience?: AudienceDetails | string;
  tone_or_purpose?: string;
  max_results?: number;
  run_gates?: boolean;
  max_rewrite_iterations?: number;
}

/** Response from POST /full-pipeline. */
export interface FullPipelineResponse {
  status: string;
  work_dir: string;
  title_choices: TitleChoiceResponse[];
  outline: string;
  draft_preview?: string;
}
