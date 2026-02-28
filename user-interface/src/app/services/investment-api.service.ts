import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  CreateProfileRequest,
  CreateProfileResponse,
  GetProfileResponse,
  CreateProposalRequest,
  CreateProposalResponse,
  GetProposalResponse,
  ValidateProposalRequest,
  ValidateProposalResponse,
  CreateStrategyRequest,
  CreateStrategyResponse,
  ValidateStrategyRequest,
  ValidateStrategyResponse,
  PromotionDecisionRequest,
  PromotionDecisionResponse,
  WorkflowStatusResponse,
  QueuesResponse,
  CreateMemoRequest,
  CreateMemoResponse,
  InvestmentHealthResponse,
} from '../models';

/**
 * Service for Investment Team API endpoints.
 * Base URL from environment.investmentApiUrl.
 */
@Injectable({ providedIn: 'root' })
export class InvestmentApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.investmentApiUrl;

  // ---------------------------------------------------------------------------
  // Health Check
  // ---------------------------------------------------------------------------

  healthCheck(): Observable<InvestmentHealthResponse> {
    return this.http.get<InvestmentHealthResponse>(`${this.baseUrl}/health`);
  }

  // ---------------------------------------------------------------------------
  // Profiles / IPS
  // ---------------------------------------------------------------------------

  createProfile(request: CreateProfileRequest): Observable<CreateProfileResponse> {
    return this.http.post<CreateProfileResponse>(
      `${this.baseUrl}/profiles`,
      request
    );
  }

  getProfile(userId: string): Observable<GetProfileResponse> {
    return this.http.get<GetProfileResponse>(
      `${this.baseUrl}/profiles/${userId}`
    );
  }

  // ---------------------------------------------------------------------------
  // Portfolio Proposals
  // ---------------------------------------------------------------------------

  createProposal(request: CreateProposalRequest): Observable<CreateProposalResponse> {
    return this.http.post<CreateProposalResponse>(
      `${this.baseUrl}/proposals/create`,
      request
    );
  }

  getProposal(proposalId: string): Observable<GetProposalResponse> {
    return this.http.get<GetProposalResponse>(
      `${this.baseUrl}/proposals/${proposalId}`
    );
  }

  validateProposal(
    proposalId: string,
    request: ValidateProposalRequest
  ): Observable<ValidateProposalResponse> {
    return this.http.post<ValidateProposalResponse>(
      `${this.baseUrl}/proposals/${proposalId}/validate`,
      request
    );
  }

  // ---------------------------------------------------------------------------
  // Strategies
  // ---------------------------------------------------------------------------

  createStrategy(request: CreateStrategyRequest): Observable<CreateStrategyResponse> {
    return this.http.post<CreateStrategyResponse>(
      `${this.baseUrl}/strategies`,
      request
    );
  }

  validateStrategy(
    strategyId: string,
    request?: ValidateStrategyRequest
  ): Observable<ValidateStrategyResponse> {
    return this.http.post<ValidateStrategyResponse>(
      `${this.baseUrl}/strategies/${strategyId}/validate`,
      request ?? {}
    );
  }

  // ---------------------------------------------------------------------------
  // Promotion
  // ---------------------------------------------------------------------------

  promotionDecision(request: PromotionDecisionRequest): Observable<PromotionDecisionResponse> {
    return this.http.post<PromotionDecisionResponse>(
      `${this.baseUrl}/promotions/decide`,
      request
    );
  }

  // ---------------------------------------------------------------------------
  // Workflow
  // ---------------------------------------------------------------------------

  getWorkflowStatus(): Observable<WorkflowStatusResponse> {
    return this.http.get<WorkflowStatusResponse>(
      `${this.baseUrl}/workflow/status`
    );
  }

  getQueues(): Observable<QueuesResponse> {
    return this.http.get<QueuesResponse>(
      `${this.baseUrl}/workflow/queues`
    );
  }

  // ---------------------------------------------------------------------------
  // Memos
  // ---------------------------------------------------------------------------

  createMemo(request: CreateMemoRequest): Observable<CreateMemoResponse> {
    return this.http.post<CreateMemoResponse>(
      `${this.baseUrl}/memos`,
      request
    );
  }
}
