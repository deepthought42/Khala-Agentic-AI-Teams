/** Request for POST /run-team. */
export interface RunTeamRequest {
  repo_path: string;
  clarification_session_id?: string;
}

/** Response from POST /run-team. */
export interface RunTeamResponse {
  job_id: string;
  status: string;
  message: string;
}

/** Detail about a single failed task. */
export interface FailedTaskDetail {
  task_id: string;
  title?: string;
  reason?: string;
}

/** Response from GET /run-team/{job_id}. */
export interface JobStatusResponse {
  job_id: string;
  status: string;
  repo_path?: string;
  requirements_title?: string;
  architecture_overview?: string;
  current_task?: string;
  task_results: unknown[];
  task_ids: string[];
  progress?: number;
  error?: string;
  failed_tasks: FailedTaskDetail[];
}

/** Response from POST /run-team/{job_id}/retry-failed. */
export interface RetryResponse {
  job_id: string;
  status: string;
  retrying_tasks: string[];
  message: string;
}

/** Request for POST /run-team/{job_id}/re-plan-with-clarifications. */
export interface RePlanWithClarificationsRequest {
  clarification_session_id: string;
}

/** Request for POST /clarification/sessions. */
export interface ClarificationCreateRequest {
  spec_text: string;
}

/** Request for POST /clarification/sessions/{id}/messages. */
export interface ClarificationMessageRequest {
  message: string;
}

/** Response from clarification endpoints. */
export interface ClarificationResponse {
  session_id: string;
  assistant_message: string;
  open_questions: string[];
  assumptions: string[];
  done_clarifying: boolean;
  refined_spec?: string;
}

/** Response from GET /clarification/sessions/{id}. */
export interface ClarificationSessionResponse {
  session_id: string;
  spec_text: string;
  status: string;
  created_at: string;
  clarification_round: number;
  max_rounds: number;
  confidence_score: number;
  open_questions: string[];
  assumptions: string[];
  refined_spec?: string;
  turns: Array<{ role: string; message: string; timestamp?: string }>;
}
