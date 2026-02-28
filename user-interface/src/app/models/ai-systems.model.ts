/**
 * Models for the AI Systems Team API.
 */

/** Phases in the AI system generation workflow. */
export type AISystemPhase =
  | 'spec_intake'
  | 'architecture'
  | 'capabilities'
  | 'evaluation'
  | 'safety'
  | 'build';

/** Orchestration patterns for agent systems. */
export type OrchestrationPattern =
  | 'sequential'
  | 'parallel'
  | 'hierarchical'
  | 'event_driven'
  | 'hybrid';

/** Phase definition for UI display. */
export interface AISystemPhaseDefinition {
  id: AISystemPhase;
  label: string;
  icon: string;
  progress: number;
}

/** AI System phases for stepper display. */
export const AI_SYSTEM_PHASES: AISystemPhaseDefinition[] = [
  { id: 'spec_intake', label: 'Spec Intake', icon: 'description', progress: 15 },
  { id: 'architecture', label: 'Architecture', icon: 'account_tree', progress: 35 },
  { id: 'capabilities', label: 'Capabilities', icon: 'build', progress: 55 },
  { id: 'evaluation', label: 'Evaluation', icon: 'checklist', progress: 75 },
  { id: 'safety', label: 'Safety', icon: 'security', progress: 90 },
  { id: 'build', label: 'Build', icon: 'rocket_launch', progress: 100 },
];

/** Request to start an AI system build job. */
export interface AISystemRequest {
  project_name: string;
  spec_path: string;
  constraints?: Record<string, unknown>;
  output_dir?: string;
}

/** Response when starting an AI system build job. */
export interface AISystemJobResponse {
  job_id: string;
  status: string;
  message: string;
}

/** Agent role in the system. */
export interface AgentRole {
  name: string;
  description: string;
  capabilities: string[];
  tools: string[];
  inputs: string[];
  outputs: string[];
}

/** Handoff rule between agents. */
export interface HandoffRule {
  from_agent: string;
  to_agent: string;
  condition: string;
  data_passed: string[];
}

/** Orchestration graph for the agent system. */
export interface OrchestrationGraph {
  pattern: OrchestrationPattern;
  agents: AgentRole[];
  handoffs: HandoffRule[];
  entry_point?: string;
  exit_points: string[];
}

/** Tool contract. */
export interface ToolContract {
  name: string;
  description: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  error_handling: string;
  rate_limits?: string;
}

/** Memory policy. */
export interface MemoryPolicy {
  session_memory: boolean;
  long_term_memory: boolean;
  retrieval_enabled: boolean;
  audit_trail: boolean;
  retention_days: number;
}

/** Safety checkpoint. */
export interface SafetyCheckpoint {
  name: string;
  description: string;
  trigger: string;
  action: string;
  requires_human_approval: boolean;
}

/** Acceptance test. */
export interface AcceptanceTest {
  name: string;
  description: string;
  input_scenario: string;
  expected_outcome: string;
  pass_criteria: string;
}

/** Key performance indicator. */
export interface KPI {
  name: string;
  description: string;
  metric: string;
  target_value: string;
  measurement_method: string;
}

/** Evaluation harness. */
export interface EvaluationHarness {
  acceptance_tests: AcceptanceTest[];
  adversarial_tests: string[];
  kpis: KPI[];
  pass_threshold: number;
}

/** Rollout stage. */
export interface RolloutStage {
  name: string;
  description: string;
  criteria_to_advance: string;
  rollback_criteria: string;
}

/** Rollout plan. */
export interface RolloutPlan {
  stages: RolloutStage[];
}

/** Spec intake result. */
export interface SpecIntakeResult {
  success: boolean;
  goals: string[];
  non_goals: string[];
  assumptions: string[];
  constraints: string[];
  allowed_actions: string[];
  disallowed_actions: string[];
  human_approval_points: string[];
  quality_expectations: Record<string, string>;
  error?: string;
}

/** Architecture result. */
export interface ArchitectureResult {
  success: boolean;
  orchestration?: OrchestrationGraph;
  rationale: string;
  error?: string;
}

/** Capabilities result. */
export interface CapabilitiesResult {
  success: boolean;
  tool_contracts: ToolContract[];
  memory_policy?: MemoryPolicy;
  model_requirements: Record<string, string>;
  error?: string;
}

/** Evaluation result. */
export interface EvaluationResult {
  success: boolean;
  harness?: EvaluationHarness;
  error?: string;
}

/** Safety result. */
export interface SafetyResult {
  success: boolean;
  checkpoints: SafetyCheckpoint[];
  guardrails: string[];
  policy_requirements: string[];
  error?: string;
}

/** Build result. */
export interface BuildResult {
  success: boolean;
  artifacts: string[];
  rollout_plan?: RolloutPlan;
  finalized_at?: string;
  error?: string;
}

/** Complete AI agent system blueprint. */
export interface AgentBlueprint {
  project_name: string;
  version: string;
  created_at?: string;
  spec_intake?: SpecIntakeResult;
  architecture?: ArchitectureResult;
  capabilities?: CapabilitiesResult;
  evaluation?: EvaluationResult;
  safety?: SafetyResult;
  build?: BuildResult;
  current_phase: AISystemPhase;
  completed_phases: AISystemPhase[];
  success: boolean;
  error?: string;
}

/** Job status response. */
export interface AISystemStatusResponse {
  job_id: string;
  status: string;
  project_name?: string;
  current_phase?: AISystemPhase;
  progress: number;
  completed_phases: string[];
  error?: string;
  blueprint?: AgentBlueprint;
}

/** Job summary for listing. */
export interface AISystemJobSummary {
  job_id: string;
  project_name: string;
  status: string;
  created_at?: string;
  current_phase?: string;
  progress: number;
}

/** Response for listing jobs. */
export interface AISystemJobsListResponse {
  jobs: AISystemJobSummary[];
}

/** Health check response. */
export interface AISystemsHealthResponse {
  status: string;
  service: string;
}
