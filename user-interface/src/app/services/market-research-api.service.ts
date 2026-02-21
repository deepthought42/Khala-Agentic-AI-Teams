import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  RunMarketResearchRequest,
  TeamOutput,
  HealthResponse,
} from '../models';

/**
 * Service for Market Research API endpoints.
 * Base URL from environment.marketResearchApiUrl (default port 8011).
 */
@Injectable({ providedIn: 'root' })
export class MarketResearchApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.marketResearchApiUrl;

  /**
   * POST /market-research/run
   * Runs market research and concept viability workflow.
   */
  run(request: RunMarketResearchRequest): Observable<TeamOutput> {
    return this.http.post<TeamOutput>(
      `${this.baseUrl}/market-research/run`,
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
