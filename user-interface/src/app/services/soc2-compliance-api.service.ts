import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  RunAuditRequest,
  RunAuditResponse,
  AuditStatusResponse,
  HealthResponse,
} from '../models';

/**
 * Service for SOC2 Compliance API endpoints.
 * Base URL from environment.soc2ComplianceApiUrl (default port 8020).
 */
@Injectable({ providedIn: 'root' })
export class Soc2ComplianceApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.soc2ComplianceApiUrl;

  /**
   * POST /soc2-audit/run
   * Starts a background SOC2 compliance audit.
   */
  runAudit(request: RunAuditRequest): Observable<RunAuditResponse> {
    return this.http.post<RunAuditResponse>(
      `${this.baseUrl}/soc2-audit/run`,
      request
    );
  }

  /**
   * GET /soc2-audit/status/{job_id}
   * Returns current status and result when completed.
   */
  getStatus(jobId: string): Observable<AuditStatusResponse> {
    return this.http.get<AuditStatusResponse>(
      `${this.baseUrl}/soc2-audit/status/${jobId}`
    );
  }

  /**
   * GET /health
   */
  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.baseUrl}/health`);
  }
}
