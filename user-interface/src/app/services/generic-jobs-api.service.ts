/**
 * Generic job management service that proxies to the unified API's
 * /api/jobs/{team}/{jobId} endpoints.  Works for any team — used as
 * a universal fallback when a team doesn't expose its own lifecycle
 * endpoints (cancel, delete, etc.).
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

const API_BASE = 'http://localhost:8888';

@Injectable({ providedIn: 'root' })
export class GenericJobsApiService {
  private readonly http = inject(HttpClient);

  cancel(team: string, jobId: string): Observable<unknown> {
    return this.http.post(`${API_BASE}/api/jobs/${team}/${encodeURIComponent(jobId)}/cancel`, {});
  }

  resume(team: string, jobId: string): Observable<unknown> {
    return this.http.post(`${API_BASE}/api/jobs/${team}/${encodeURIComponent(jobId)}/resume`, {});
  }

  restart(team: string, jobId: string): Observable<unknown> {
    return this.http.post(`${API_BASE}/api/jobs/${team}/${encodeURIComponent(jobId)}/restart`, {});
  }

  interrupt(team: string, jobId: string): Observable<unknown> {
    return this.http.post(`${API_BASE}/api/jobs/${team}/${encodeURIComponent(jobId)}/interrupt`, {});
  }

  delete(team: string, jobId: string): Observable<unknown> {
    return this.http.delete(`${API_BASE}/api/jobs/${team}/${encodeURIComponent(jobId)}`);
  }

  markAllInterrupted(team: string): Observable<unknown> {
    return this.http.post(`${API_BASE}/api/jobs/${team}/mark-all-interrupted`, {});
  }
}
