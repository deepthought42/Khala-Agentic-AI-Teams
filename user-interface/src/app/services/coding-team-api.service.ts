import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type { HealthResponse } from '../models/health.model';

/**
 * Coding Team API (Software Engineering sub-team). Base URL from environment.codingTeamApiUrl.
 */
@Injectable({ providedIn: 'root' })
export class CodingTeamApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.codingTeamApiUrl;

  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.baseUrl}/health`);
  }
}
