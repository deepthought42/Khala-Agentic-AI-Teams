import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import { LoadingSpinnerComponent } from '../../shared/loading-spinner/loading-spinner.component';
import { ErrorMessageComponent } from '../../shared/error-message/error-message.component';
import { HealthIndicatorComponent } from '../health-indicator/health-indicator.component';
import { RunTeamFormComponent } from '../run-team-form/run-team-form.component';
import { JobStatusComponent } from '../job-status/job-status.component';
import { RetryFailedComponent } from '../retry-failed/retry-failed.component';
import { RePlanWithClarificationsComponent } from '../re-plan-with-clarifications/re-plan-with-clarifications.component';
import { ClarificationSessionsComponent } from '../clarification-sessions/clarification-sessions.component';
import { ClarificationChatComponent } from '../clarification-chat/clarification-chat.component';
import { ExecutionTasksComponent } from '../execution-tasks/execution-tasks.component';
import { ExecutionStreamComponent } from '../execution-stream/execution-stream.component';
import { ArchitectureResultsComponent } from '../architecture-results/architecture-results.component';
import { BackendCodeV2RunFormComponent } from '../backend-code-v2-run-form/backend-code-v2-run-form.component';
import { BackendCodeV2JobStatusComponent } from '../backend-code-v2-job-status/backend-code-v2-job-status.component';
import { FrontendAgentV2RunFormComponent } from '../frontend-agent-v2-run-form/frontend-agent-v2-run-form.component';
import { FrontendAgentV2JobStatusComponent } from '../frontend-agent-v2-job-status/frontend-agent-v2-job-status.component';
import type {
  RunTeamRequest,
  JobStatusResponse,
  RePlanWithClarificationsRequest,
  ClarificationCreateRequest,
  ArchitectDesignResponse,
  BackendCodeV2RunRequest,
  FrontendAgentV2RunRequest,
} from '../../models';

@Component({
  selector: 'app-software-engineering-dashboard',
  standalone: true,
  imports: [
    FormsModule,
    MatTabsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    LoadingSpinnerComponent,
    ErrorMessageComponent,
    HealthIndicatorComponent,
    RunTeamFormComponent,
    JobStatusComponent,
    RetryFailedComponent,
    RePlanWithClarificationsComponent,
    ClarificationSessionsComponent,
    ClarificationChatComponent,
    ExecutionTasksComponent,
    ExecutionStreamComponent,
    ArchitectureResultsComponent,
    BackendCodeV2RunFormComponent,
    BackendCodeV2JobStatusComponent,
    FrontendAgentV2RunFormComponent,
    FrontendAgentV2JobStatusComponent,
  ],
  templateUrl: './software-engineering-dashboard.component.html',
  styleUrl: './software-engineering-dashboard.component.scss',
})
export class SoftwareEngineeringDashboardComponent {
  private readonly api = inject(SoftwareEngineeringApiService);

  loading = false;
  error: string | null = null;
  jobId: string | null = null;
  jobStatus: { failed_tasks?: unknown[] } | null = null;
  clarificationSessionId: string | null = null;
  architectSpec = '';
  architectResults: ArchitectDesignResponse | null = null;
  backendCodeV2JobId: string | null = null;
  frontendAgentV2JobId: string | null = null;

  healthCheck = (): ReturnType<SoftwareEngineeringApiService['health']> =>
    this.api.health();

  onRunTeamSubmit(request: RunTeamRequest): void {
    this.loading = true;
    this.error = null;
    this.jobId = null;
    this.api.runTeam(request).subscribe({
      next: (res) => {
        this.jobId = res.job_id;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Request failed';
        this.loading = false;
      },
    });
  }

  onRetryFailed(): void {
    if (!this.jobId) return;
    this.loading = true;
    this.error = null;
    this.api.retryFailed(this.jobId).subscribe({
      next: () => {
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Retry failed';
        this.loading = false;
      },
    });
  }

  onRePlanSubmit(request: RePlanWithClarificationsRequest): void {
    if (!this.jobId) return;
    this.loading = true;
    this.error = null;
    this.api.rePlanWithClarifications(this.jobId, request).subscribe({
      next: () => {
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Re-plan failed';
        this.loading = false;
      },
    });
  }

  onClarificationSessionCreate(request: ClarificationCreateRequest): void {
    this.error = null;
    this.api.createClarificationSession(request).subscribe({
      next: (res) => {
        this.clarificationSessionId = res.session_id;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Create session failed';
      },
    });
  }

  onBackendCodeV2Submit(request: BackendCodeV2RunRequest): void {
    this.loading = true;
    this.error = null;
    this.backendCodeV2JobId = null;
    this.api.runBackendCodeV2(request).subscribe({
      next: (res) => {
        this.backendCodeV2JobId = res.job_id;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Backend-Code-V2 request failed';
        this.loading = false;
      },
    });
  }

  onArchitectDesignSubmit(): void {
    if (!this.architectSpec?.trim()) return;
    this.loading = true;
    this.error = null;
    this.architectResults = null;
    this.api.architectDesign({ spec: this.architectSpec.trim() }).subscribe({
      next: (res) => {
        this.architectResults = res;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Architecture design failed';
        this.loading = false;
      },
    });
  }

  onFrontendAgentV2Submit(request: FrontendAgentV2RunRequest): void {
    this.loading = true;
    this.error = null;
    this.frontendAgentV2JobId = null;
    this.api.runFrontendAgentV2(request).subscribe({
      next: (res) => {
        this.frontendAgentV2JobId = res.job_id;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Frontend-Agent-V2 request failed';
        this.loading = false;
      },
    });
  }
}
