import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  IntegrationListItem,
  MediumConfigResponse,
  MediumConfigUpdate,
  MediumGoogleOAuthConnectResponse,
  MediumSessionImportBody,
  SlackConfigResponse,
  SlackConfigUpdate,
  SlackOAuthConnectResponse,
} from '../models/integrations.model';

/**
 * Service for Integrations API (Slack config, OAuth, etc.).
 * Base URL from environment.integrationsApiUrl.
 */
@Injectable({ providedIn: 'root' })
export class IntegrationsApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.integrationsApiUrl;

  /** GET /api/integrations - list integrations. */
  getIntegrations(): Observable<IntegrationListItem[]> {
    return this.http.get<IntegrationListItem[]>(this.baseUrl);
  }

  /** GET /api/integrations/slack - get Slack config. */
  getSlackConfig(): Observable<SlackConfigResponse> {
    return this.http.get<SlackConfigResponse>(`${this.baseUrl}/slack`);
  }

  /** PUT /api/integrations/slack - update Slack config (manual / webhook mode). */
  updateSlackConfig(body: SlackConfigUpdate): Observable<SlackConfigResponse> {
    return this.http.put<SlackConfigResponse>(`${this.baseUrl}/slack`, body);
  }

  /**
   * GET /api/integrations/slack/oauth/connect
   * Returns the Slack OAuth authorization URL to redirect the user to.
   */
  getSlackOAuthUrl(): Observable<SlackOAuthConnectResponse> {
    return this.http.get<SlackOAuthConnectResponse>(`${this.baseUrl}/slack/oauth/connect`);
  }

  /**
   * DELETE /api/integrations/slack/oauth
   * Disconnects the Slack OAuth connection (removes stored token and team info).
   */
  disconnectSlack(): Observable<SlackConfigResponse> {
    return this.http.delete<SlackConfigResponse>(`${this.baseUrl}/slack/oauth`);
  }

  /** GET /api/integrations/medium */
  getMediumConfig(): Observable<MediumConfigResponse> {
    return this.http.get<MediumConfigResponse>(`${this.baseUrl}/medium`);
  }

  /** PUT /api/integrations/medium */
  updateMediumConfig(body: MediumConfigUpdate): Observable<MediumConfigResponse> {
    return this.http.put<MediumConfigResponse>(`${this.baseUrl}/medium`, body);
  }

  /** GET /api/integrations/medium/oauth/google/connect */
  getMediumGoogleOAuthUrl(): Observable<MediumGoogleOAuthConnectResponse> {
    return this.http.get<MediumGoogleOAuthConnectResponse>(`${this.baseUrl}/medium/oauth/google/connect`);
  }

  /** DELETE /api/integrations/medium/oauth/google */
  disconnectMediumGoogle(): Observable<MediumConfigResponse> {
    return this.http.delete<MediumConfigResponse>(`${this.baseUrl}/medium/oauth/google`);
  }

  /** POST /api/integrations/medium/session */
  importMediumSession(body: MediumSessionImportBody): Observable<MediumConfigResponse> {
    return this.http.post<MediumConfigResponse>(`${this.baseUrl}/medium/session`, body);
  }

  /** DELETE /api/integrations/medium/session */
  clearMediumSession(): Observable<MediumConfigResponse> {
    return this.http.delete<MediumConfigResponse>(`${this.baseUrl}/medium/session`);
  }
}
