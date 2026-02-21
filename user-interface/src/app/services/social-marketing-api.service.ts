import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  RunMarketingTeamRequest,
  RunMarketingTeamResponse,
  MarketingJobStatusResponse,
  PerformanceIngestRequest,
  PerformanceIngestResponse,
  ReviseMarketingTeamRequest,
  HealthResponse,
} from '../models';

/**
 * Service for Social Media Marketing API endpoints.
 * Base URL from environment.socialMarketingApiUrl (default port 8010).
 */
@Injectable({ providedIn: 'root' })
export class SocialMarketingApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.socialMarketingApiUrl;

  /**
   * POST /social-marketing/run
   */
  run(request: RunMarketingTeamRequest): Observable<RunMarketingTeamResponse> {
    return this.http.post<RunMarketingTeamResponse>(
      `${this.baseUrl}/social-marketing/run`,
      request
    );
  }

  /**
   * GET /social-marketing/status/{job_id}
   */
  getStatus(jobId: string): Observable<MarketingJobStatusResponse> {
    return this.http.get<MarketingJobStatusResponse>(
      `${this.baseUrl}/social-marketing/status/${jobId}`
    );
  }

  /**
   * POST /social-marketing/performance/{job_id}
   */
  ingestPerformance(
    jobId: string,
    request: PerformanceIngestRequest
  ): Observable<PerformanceIngestResponse> {
    return this.http.post<PerformanceIngestResponse>(
      `${this.baseUrl}/social-marketing/performance/${jobId}`,
      request
    );
  }

  /**
   * POST /social-marketing/revise/{job_id}
   */
  revise(
    jobId: string,
    request: ReviseMarketingTeamRequest
  ): Observable<RunMarketingTeamResponse> {
    return this.http.post<RunMarketingTeamResponse>(
      `${this.baseUrl}/social-marketing/revise/${jobId}`,
      request
    );
  }

  /**
   * GET /health
   */
  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.baseUrl}/health`);
  }
}
