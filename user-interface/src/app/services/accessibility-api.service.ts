import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  CreateAuditRequest,
  AuditJobResponse,
  AccessibilityAuditStatusResponse,
  FindingsListResponse,
  FindingFilters,
  AuditReportResponse,
  RetestRequest,
  RetestResponse,
  ExportResponse,
  DesignSystemInventoryRequest,
  DesignSystemInventoryResponse,
  DesignSystemContractRequest,
  DesignSystemContractResponse,
  HealthResponse,
} from '../models';

/**
 * Service for Accessibility Audit Team API endpoints.
 * Base URL from environment.accessibilityApiUrl.
 */
@Injectable({ providedIn: 'root' })
export class AccessibilityApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.accessibilityApiUrl;

  // ---------------------------------------------------------------------------
  // Health Check
  // ---------------------------------------------------------------------------

  /**
   * GET /health
   */
  healthCheck(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.baseUrl}/health`);
  }

  // ---------------------------------------------------------------------------
  // Audit Lifecycle
  // ---------------------------------------------------------------------------

  /**
   * POST /audit/create - Create and start a new accessibility audit.
   */
  createAudit(request: CreateAuditRequest): Observable<AuditJobResponse> {
    return this.http.post<AuditJobResponse>(
      `${this.baseUrl}/audit/create`,
      request
    );
  }

  /**
   * GET /audit/status/{job_id} - Poll audit job status.
   */
  getJobStatus(jobId: string): Observable<AccessibilityAuditStatusResponse> {
    return this.http.get<AccessibilityAuditStatusResponse>(
      `${this.baseUrl}/audit/status/${jobId}`
    );
  }

  /**
   * GET /audit/{audit_id}/findings - Get findings with optional filters.
   */
  getFindings(
    auditId: string,
    filters?: FindingFilters
  ): Observable<FindingsListResponse> {
    let params = new HttpParams();

    if (filters?.severity?.length) {
      filters.severity.forEach((s) => {
        params = params.append('severity', s);
      });
    }
    if (filters?.issue_type?.length) {
      filters.issue_type.forEach((t) => {
        params = params.append('issue_type', t);
      });
    }
    if (filters?.wcag_level?.length) {
      filters.wcag_level.forEach((l) => {
        params = params.append('wcag_level', l);
      });
    }
    if (filters?.state?.length) {
      filters.state.forEach((s) => {
        params = params.append('state', s);
      });
    }

    return this.http.get<FindingsListResponse>(
      `${this.baseUrl}/audit/${auditId}/findings`,
      { params }
    );
  }

  /**
   * GET /audit/{audit_id}/report - Get final report for completed audit.
   */
  getReport(auditId: string): Observable<AuditReportResponse> {
    return this.http.get<AuditReportResponse>(
      `${this.baseUrl}/audit/${auditId}/report`
    );
  }

  // ---------------------------------------------------------------------------
  // Retest
  // ---------------------------------------------------------------------------

  /**
   * POST /audit/{audit_id}/retest - Run retest on specific findings.
   */
  retestFindings(
    auditId: string,
    request: RetestRequest
  ): Observable<RetestResponse> {
    return this.http.post<RetestResponse>(
      `${this.baseUrl}/audit/${auditId}/retest`,
      request
    );
  }

  // ---------------------------------------------------------------------------
  // Export
  // ---------------------------------------------------------------------------

  /**
   * POST /audit/{audit_id}/export - Export backlog as JSON or CSV.
   * Returns blob for file download.
   */
  exportBacklog(
    auditId: string,
    format: 'json' | 'csv'
  ): Observable<ExportResponse> {
    return this.http.post<ExportResponse>(
      `${this.baseUrl}/audit/${auditId}/export`,
      { format }
    );
  }

  /**
   * Download export file as blob for direct download.
   */
  downloadExport(
    auditId: string,
    format: 'json' | 'csv'
  ): Observable<Blob> {
    return this.http.post(
      `${this.baseUrl}/audit/${auditId}/export`,
      { format },
      { responseType: 'blob' }
    );
  }

  // ---------------------------------------------------------------------------
  // Design System (ADSE Add-on)
  // ---------------------------------------------------------------------------

  /**
   * POST /designsystem/inventory - Build design system component inventory.
   */
  buildDesignSystemInventory(
    request: DesignSystemInventoryRequest
  ): Observable<DesignSystemInventoryResponse> {
    return this.http.post<DesignSystemInventoryResponse>(
      `${this.baseUrl}/designsystem/inventory`,
      request
    );
  }

  /**
   * POST /designsystem/contract - Generate a11y contract for component.
   */
  generateDesignSystemContract(
    request: DesignSystemContractRequest
  ): Observable<DesignSystemContractResponse> {
    return this.http.post<DesignSystemContractResponse>(
      `${this.baseUrl}/designsystem/contract`,
      request
    );
  }
}
