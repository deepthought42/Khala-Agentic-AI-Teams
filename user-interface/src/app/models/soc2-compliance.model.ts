/** Request for POST /soc2-audit/run. */
export interface RunAuditRequest {
  repo_path: string;
}

/** Response from POST /soc2-audit/run. */
export interface RunAuditResponse {
  job_id: string;
  status: string;
  message: string;
}

/** TSC finding severity. */
export type FindingSeverity =
  | 'critical'
  | 'high'
  | 'medium'
  | 'low'
  | 'informational';

/** TSC category. */
export type TSCCategory =
  | 'security'
  | 'availability'
  | 'processing_integrity'
  | 'confidentiality'
  | 'privacy';

/** A single SOC2 compliance finding. */
export interface TSCFinding {
  severity: FindingSeverity;
  category: TSCCategory;
  title: string;
  description: string;
  location?: string;
  recommendation?: string;
  evidence_observed?: string;
}

/** Audit result for one TSC. */
export interface TSCAuditResult {
  category: TSCCategory;
  summary?: string;
  findings: TSCFinding[];
  compliant?: boolean;
}

/** Full SOC2 audit result. */
export interface SOC2AuditResult {
  executive_summary?: string;
  scope?: string;
  findings_by_tsc?: Record<string, TSCFinding[]>;
  recommendations_summary?: string[];
  report_type?: string;
  raw_markdown?: string;
}

/** Response from GET /soc2-audit/status/{job_id}. */
export interface AuditStatusResponse {
  job_id: string;
  status: string;
  repo_path?: string;
  current_stage?: string;
  last_updated_at?: string;
  error?: string;
  result?: SOC2AuditResult;
}
