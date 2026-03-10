import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  AISystemRequest,
  AISystemJobResponse,
  AISystemStatusResponse,
  AISystemJobsListResponse,
  AgentBlueprint,
  AISystemsHealthResponse,
} from '../models';

/**
 * API service for the AI Systems Team.
 */
@Injectable({ providedIn: 'root' })
export class AISystemsApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.aiSystemsApiUrl;

  /** Health check. */
  healthCheck(): Observable<AISystemsHealthResponse> {
    return this.http.get<AISystemsHealthResponse>(`${this.baseUrl}/health`);
  }

  /** Start a new AI system build job. */
  startBuild(request: AISystemRequest): Observable<AISystemJobResponse> {
    return this.http.post<AISystemJobResponse>(`${this.baseUrl}/build`, request);
  }

  /** Get the status of a build job. */
  getJobStatus(jobId: string): Observable<AISystemStatusResponse> {
    return this.http.get<AISystemStatusResponse>(`${this.baseUrl}/build/status/${jobId}`);
  }

  /** List all build jobs. */
  listJobs(runningOnly = false): Observable<AISystemJobsListResponse> {
    let params = new HttpParams();
    if (runningOnly) {
      params = params.set('running_only', 'true');
    }
    return this.http.get<AISystemJobsListResponse>(`${this.baseUrl}/build/jobs`, { params });
  }

  /** Cancel a pending or running build job. */
  cancelJob(jobId: string): Observable<{ job_id: string; status: string; message: string }> {
    return this.http.post<{ job_id: string; status: string; message: string }>(
      `${this.baseUrl}/build/job/${jobId}/cancel`,
      {}
    );
  }

  /** Delete a build job from the store. */
  deleteJob(jobId: string): Observable<{ job_id: string; message: string }> {
    return this.http.delete<{ job_id: string; message: string }>(
      `${this.baseUrl}/build/job/${jobId}`
    );
  }

  /** List all generated blueprints. */
  listBlueprints(): Observable<{ blueprints: string[] }> {
    return this.http.get<{ blueprints: string[] }>(`${this.baseUrl}/blueprints`);
  }

  /** Get a blueprint by project name. */
  getBlueprint(projectName: string): Observable<AgentBlueprint> {
    return this.http.get<AgentBlueprint>(`${this.baseUrl}/blueprints/${encodeURIComponent(projectName)}`);
  }
}
