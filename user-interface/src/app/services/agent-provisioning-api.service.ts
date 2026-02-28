import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  ProvisionRequest,
  ProvisionJobResponse,
  ProvisionStatusResponse,
  ProvisionJobsListResponse,
  AgentStatusResponse,
  AgentListResponse,
  ProvisioningHealthResponse,
} from '../models';

/**
 * API service for the Agent Provisioning Team.
 */
@Injectable({ providedIn: 'root' })
export class AgentProvisioningApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.agentProvisioningApiUrl;

  /** Health check. */
  healthCheck(): Observable<ProvisioningHealthResponse> {
    return this.http.get<ProvisioningHealthResponse>(`${this.baseUrl}/health`);
  }

  /** Start a new provisioning job. */
  startProvisioning(request: ProvisionRequest): Observable<ProvisionJobResponse> {
    return this.http.post<ProvisionJobResponse>(`${this.baseUrl}/provision`, request);
  }

  /** Get the status of a provisioning job. */
  getJobStatus(jobId: string): Observable<ProvisionStatusResponse> {
    return this.http.get<ProvisionStatusResponse>(`${this.baseUrl}/provision/status/${jobId}`);
  }

  /** List all provisioning jobs. */
  listJobs(runningOnly = false): Observable<ProvisionJobsListResponse> {
    let params = new HttpParams();
    if (runningOnly) {
      params = params.set('running_only', 'true');
    }
    return this.http.get<ProvisionJobsListResponse>(`${this.baseUrl}/provision/jobs`, { params });
  }

  /** Get the status of a provisioned agent environment. */
  getAgentStatus(agentId: string): Observable<AgentStatusResponse> {
    return this.http.get<AgentStatusResponse>(`${this.baseUrl}/environments/${agentId}`);
  }

  /** List all provisioned agent environments. */
  listAgents(status?: string): Observable<AgentListResponse> {
    let params = new HttpParams();
    if (status) {
      params = params.set('status', status);
    }
    return this.http.get<AgentListResponse>(`${this.baseUrl}/environments`, { params });
  }

  /** Deprovision an agent environment. */
  deprovisionAgent(agentId: string, force = false): Observable<{ agent_id: string; success: boolean; error?: string }> {
    let params = new HttpParams();
    if (force) {
      params = params.set('force', 'true');
    }
    return this.http.delete<{ agent_id: string; success: boolean; error?: string }>(
      `${this.baseUrl}/environments/${agentId}`,
      { params }
    );
  }
}
