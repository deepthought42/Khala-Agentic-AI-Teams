/**
 * Models for the Accessibility Audit Team API.
 */

// ---------------------------------------------------------------------------
// Enums and Constants
// ---------------------------------------------------------------------------

export type AuditType = 'webpage' | 'website' | 'spa' | 'mobile';

export type Surface = 'web' | 'ios' | 'android' | 'pdf';

export type Severity = 'Critical' | 'High' | 'Medium' | 'Low';

export type Scope = 'Systemic' | 'Multi-area' | 'Localized';

export type FindingState =
  | 'draft'
  | 'needs_verification'
  | 'verified'
  | 'ready_for_report'
  | 'closed';

export type IssueType =
  | 'name_role_value'
  | 'keyboard'
  | 'focus'
  | 'forms'
  | 'contrast'
  | 'structure'
  | 'timing'
  | 'media'
  | 'motion'
  | 'input_modality'
  | 'error_handling'
  | 'navigation'
  | 'resizing_reflow'
  | 'gestures_dragging'
  | 'target_size';

export type WCAGLevel = 'A' | 'AA' | 'AAA';

export type SamplingStrategy = 'journey_based' | 'template_based' | 'risk_based';

export type AuditPhase =
  | 'intake'
  | 'discovery'
  | 'verification'
  | 'report_packaging'
  | 'retest';

/** Phase definitions for accessibility audit stepper. */
export interface AccessibilityPhaseDefinition {
  id: AuditPhase;
  label: string;
  icon: string;
}

export const ACCESSIBILITY_AUDIT_PHASES: AccessibilityPhaseDefinition[] = [
  { id: 'intake', label: 'Intake', icon: 'input' },
  { id: 'discovery', label: 'Discovery', icon: 'search' },
  { id: 'verification', label: 'Verification', icon: 'verified' },
  { id: 'report_packaging', label: 'Report', icon: 'summarize' },
  { id: 'retest', label: 'Retest', icon: 'replay' },
];

// ---------------------------------------------------------------------------
// Mobile App Target
// ---------------------------------------------------------------------------

export interface MobileAppTarget {
  platform: 'ios' | 'android';
  name: string;
  version: string;
  build?: string;
}

// ---------------------------------------------------------------------------
// Request Models
// ---------------------------------------------------------------------------

/** Request for POST /audit/create. */
export interface CreateAuditRequest {
  name: string;
  web_urls: string[];
  mobile_apps: MobileAppTarget[];
  critical_journeys: string[];
  timebox_hours?: number;
  auth_required: boolean;
  max_pages?: number;
  sampling_strategy: SamplingStrategy;
  wcag_levels: WCAGLevel[];
  tech_stack?: { web?: string; mobile?: string };
}

/** Request for POST /audit/{audit_id}/retest. */
export interface RetestRequest {
  finding_ids: string[];
}

/** Request for POST /audit/{audit_id}/export. */
export interface ExportRequest {
  format: 'json' | 'csv';
}

/** Request for POST /designsystem/inventory. */
export interface DesignSystemInventoryRequest {
  system_name: string;
  source: 'storybook' | 'repo' | 'manual';
  components?: string[];
}

/** Request for POST /designsystem/contract. */
export interface DesignSystemContractRequest {
  system_name: string;
  component: string;
  platform: Surface;
  linked_patterns?: string[];
}

// ---------------------------------------------------------------------------
// Response Models
// ---------------------------------------------------------------------------

/** Response from POST /audit/create. */
export interface AuditJobResponse {
  job_id: string;
  audit_id: string;
  status: string;
  message: string;
}

/** Response from GET /audit/status/{job_id}. */
export interface AccessibilityAuditStatusResponse {
  job_id: string;
  audit_id: string;
  status: 'running' | 'complete' | 'failed' | 'cancelled';
  current_phase?: AuditPhase;
  progress: number;
  completed_phases: AuditPhase[];
  findings_count: number;
  error?: string;
  result?: AccessibilityAuditResult;
}

/** Response from POST /audit/{audit_id}/retest. */
export interface RetestResponse {
  job_id: string;
  audit_id: string;
  status: string;
  message: string;
  findings_retested: number;
}

/** Response from POST /audit/{audit_id}/export. */
export interface ExportResponse {
  audit_id: string;
  format: string;
  artifact_ref: string;
  counts: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Finding Models
// ---------------------------------------------------------------------------

/** WCAG success criteria mapping. */
export interface WCAGMapping {
  sc: string;
  name: string;
  confidence: number;
  rationale?: string;
}

/** A single accessibility finding. */
export interface Finding {
  id: string;
  state: FindingState;
  surface: Surface;
  target: string;
  issue_type: IssueType;
  severity: Severity;
  scope: Scope;
  confidence: number;

  title: string;
  summary: string;
  repro_steps: string[];
  expected: string;
  actual: string;
  user_impact: string;

  wcag_mappings: WCAGMapping[];
  section_508_tags?: string[];

  evidence_pack_ref?: string;

  root_cause_hypothesis?: string;
  recommended_fix: string[];
  acceptance_criteria: string[];
  test_plan?: string[];
  code_examples_ref?: string;

  pattern_id?: string;
  component_id?: string;
  duplicate_of?: string;

  created_at?: string;
  updated_at?: string;
  created_by?: string;
  verified_by?: string;
}

/** Response from GET /audit/{audit_id}/findings. */
export interface FindingsListResponse {
  audit_id: string;
  total: number;
  findings: Finding[];
  by_severity: Record<Severity, number>;
  by_issue_type: Record<IssueType, number>;
}

/** Filters for findings list. */
export interface FindingFilters {
  severity?: Severity[];
  issue_type?: IssueType[];
  wcag_level?: WCAGLevel[];
  state?: FindingState[];
}

// ---------------------------------------------------------------------------
// Audit Result Models
// ---------------------------------------------------------------------------

/** Pattern cluster for grouping related findings. */
export interface PatternCluster {
  pattern_id: string;
  name: string;
  description?: string;
  linked_finding_ids: string[];
  severity: Severity;
  scope: Scope;
  issue_types: IssueType[];
  wcag_scs: string[];
  component_ids?: string[];
  fix_priority: number;
}

/** Complete accessibility audit result. */
export interface AccessibilityAuditResult {
  audit_id: string;
  success: boolean;
  current_phase: AuditPhase;
  completed_phases: AuditPhase[];

  total_findings: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;

  final_findings?: Finding[];
  final_patterns?: PatternCluster[];

  summary?: string;
  failure_reason?: string;
  started_at?: string;
  completed_at?: string;
}

/** Response from GET /audit/{audit_id}/report. */
export interface AuditReportResponse {
  audit_id: string;
  executive_summary: string;
  total_findings: number;
  by_severity: Record<Severity, number>;
  by_issue_type: Record<string, number>;
  roadmap: string[];
  coverage_summary?: string;
  patterns: PatternCluster[];
}

// ---------------------------------------------------------------------------
// Design System Models
// ---------------------------------------------------------------------------

/** Response from POST /designsystem/inventory. */
export interface DesignSystemInventoryResponse {
  inventory_ref: string;
  system_name: string;
  source: string;
  components: string[];
  created_at: string;
}

/** Response from POST /designsystem/contract. */
export interface DesignSystemContractResponse {
  contract_ref: string;
  system_name: string;
  component: string;
  platform: Surface;
  requirements: Record<string, unknown>;
  test_harness_plan: Record<string, unknown>;
  linked_patterns: string[];
  created_at: string;
}

// ---------------------------------------------------------------------------
// Health Check
// ---------------------------------------------------------------------------

export interface AccessibilityHealthResponse {
  status: string;
  service?: string;
  version?: string;
}
