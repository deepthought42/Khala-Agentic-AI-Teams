import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  ResearchAndReviewRequest,
  ResearchAndReviewResponse,
  FullPipelineRequest,
  FullPipelineResponse,
  HealthResponse,
} from '../models';

/**
 * Service for Blogging API endpoints.
 * Base URL from environment.bloggingApiUrl (default port 8000).
 */
@Injectable({ providedIn: 'root' })
export class BloggingApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.bloggingApiUrl;

  /**
   * POST /research-and-review
   * Runs research and review pipeline; returns title choices and outline.
   */
  researchAndReview(
    request: ResearchAndReviewRequest
  ): Observable<ResearchAndReviewResponse> {
    return this.http.post<ResearchAndReviewResponse>(
      `${this.baseUrl}/research-and-review`,
      request
    );
  }

  /**
   * POST /full-pipeline
   * Runs full blog pipeline with gates (research, review, draft, validators, compliance).
   */
  fullPipeline(request: FullPipelineRequest): Observable<FullPipelineResponse> {
    return this.http.post<FullPipelineResponse>(
      `${this.baseUrl}/full-pipeline`,
      request
    );
  }

  /**
   * GET /health
   * Health check for the Blogging API.
   */
  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.baseUrl}/health`);
  }
}
