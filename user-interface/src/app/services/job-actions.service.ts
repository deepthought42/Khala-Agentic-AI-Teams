/**
 * Unified job action dispatcher.
 *
 * Consolidates the per-team API routing for stop, resume, restart, and delete
 * into a single service so the Jobs Dashboard doesn't need a switch statement
 * per action per team.
 */
import { Injectable, inject } from '@angular/core';
import { Observable, EMPTY } from 'rxjs';

import type { JobSource } from '../models';
import { SoftwareEngineeringApiService } from './software-engineering-api.service';
import { BloggingApiService } from './blogging-api.service';
import { AISystemsApiService } from './ai-systems-api.service';
import { AgentProvisioningApiService } from './agent-provisioning-api.service';
import { SocialMarketingApiService } from './social-marketing-api.service';
import { InvestmentApiService } from './investment-api.service';

@Injectable({ providedIn: 'root' })
export class JobActionsService {
  private readonly se = inject(SoftwareEngineeringApiService);
  private readonly blogging = inject(BloggingApiService);
  private readonly ai = inject(AISystemsApiService);
  private readonly prov = inject(AgentProvisioningApiService);
  private readonly social = inject(SocialMarketingApiService);
  private readonly investment = inject(InvestmentApiService);

  stop(source: JobSource, jobId: string): Observable<unknown> {
    switch (source) {
      case 'software_engineering': return this.se.cancelJob(jobId);
      case 'blogging': return this.blogging.cancelJob(jobId);
      case 'ai_systems': return this.ai.cancelJob(jobId);
      case 'agent_provisioning': return this.prov.cancelJob(jobId);
      case 'social_marketing': return this.social.cancelJob(jobId);
      default: return EMPTY;
    }
  }

  resume(source: JobSource, jobId: string): Observable<unknown> {
    switch (source) {
      case 'software_engineering': return this.se.resumeRunTeamJob(jobId);
      case 'blogging': return this.blogging.resumeJob(jobId);
      case 'ai_systems': return this.ai.resumeJob(jobId);
      case 'agent_provisioning': return this.prov.resumeJob(jobId);
      case 'social_marketing': return this.social.resumeJob(jobId);
      case 'investment': return this.investment.resumeRun(jobId);
      default: return EMPTY;
    }
  }

  restart(source: JobSource, jobId: string): Observable<unknown> {
    switch (source) {
      case 'software_engineering': return this.se.restartRunTeamJob(jobId);
      case 'blogging': return this.blogging.restartJob(jobId);
      case 'ai_systems': return this.ai.restartJob(jobId);
      case 'agent_provisioning': return this.prov.restartJob(jobId);
      case 'social_marketing': return this.social.restartJob(jobId);
      case 'investment': return this.investment.restartRun(jobId);
      default: return EMPTY;
    }
  }

  delete(source: JobSource, jobId: string): Observable<unknown> {
    switch (source) {
      case 'software_engineering': return this.se.deleteJob(jobId);
      case 'blogging': return this.blogging.deleteJob(jobId);
      case 'ai_systems': return this.ai.deleteJob(jobId);
      case 'agent_provisioning': return this.prov.deleteJob(jobId);
      case 'social_marketing': return this.social.deleteJob(jobId);
      default: return EMPTY;
    }
  }
}
