import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  PersonaInfo,
  PersonaTestRun,
  PersonaTestRunDetail,
  PersonaDecision,
  RunArtifacts,
} from '../models';

@Injectable({ providedIn: 'root' })
export class PersonaTestingApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.personaTestingApiUrl;

  getPersonas(): Observable<{ personas: PersonaInfo[] }> {
    return this.http.get<{ personas: PersonaInfo[] }>(`${this.baseUrl}/personas`);
  }

  startTest(): Observable<{ run_id: string; status: string; message: string }> {
    return this.http.post<{ run_id: string; status: string; message: string }>(
      `${this.baseUrl}/start`,
      {},
    );
  }

  getRuns(): Observable<{ runs: PersonaTestRun[] }> {
    return this.http.get<{ runs: PersonaTestRun[] }>(`${this.baseUrl}/runs`);
  }

  getRunStatus(runId: string): Observable<PersonaTestRunDetail> {
    return this.http.get<PersonaTestRunDetail>(`${this.baseUrl}/status/${runId}`);
  }

  getDecisions(runId: string): Observable<PersonaDecision[]> {
    return this.http.get<PersonaDecision[]>(`${this.baseUrl}/decisions/${runId}`);
  }

  getRunArtifacts(runId: string): Observable<RunArtifacts> {
    return this.http.get<RunArtifacts>(`${this.baseUrl}/runs/${runId}/artifacts`);
  }
}
