import { Component, inject } from '@angular/core';
import { MatTabsModule } from '@angular/material/tabs';
import { SocialMarketingApiService } from '../../services/social-marketing-api.service';
import { LoadingSpinnerComponent } from '../../shared/loading-spinner/loading-spinner.component';
import { ErrorMessageComponent } from '../../shared/error-message/error-message.component';
import { HealthIndicatorComponent } from '../health-indicator/health-indicator.component';
import { SocialMarketingRunFormComponent } from '../social-marketing-run-form/social-marketing-run-form.component';
import { SocialMarketingStatusComponent } from '../social-marketing-status/social-marketing-status.component';
import { SocialMarketingPerformanceComponent } from '../social-marketing-performance/social-marketing-performance.component';
import { SocialMarketingReviseComponent } from '../social-marketing-revise/social-marketing-revise.component';
import type {
  RunMarketingTeamRequest,
  PostPerformanceObservation,
  ReviseMarketingTeamRequest,
} from '../../models';

@Component({
  selector: 'app-social-marketing-dashboard',
  standalone: true,
  imports: [
    MatTabsModule,
    LoadingSpinnerComponent,
    ErrorMessageComponent,
    HealthIndicatorComponent,
    SocialMarketingRunFormComponent,
    SocialMarketingStatusComponent,
    SocialMarketingPerformanceComponent,
    SocialMarketingReviseComponent,
  ],
  templateUrl: './social-marketing-dashboard.component.html',
  styleUrl: './social-marketing-dashboard.component.scss',
})
export class SocialMarketingDashboardComponent {
  private readonly api = inject(SocialMarketingApiService);

  loading = false;
  error: string | null = null;
  jobId: string | null = null;

  healthCheck = (): ReturnType<SocialMarketingApiService['health']> =>
    this.api.health();

  onRunSubmit(request: RunMarketingTeamRequest): void {
    this.loading = true;
    this.error = null;
    this.jobId = null;
    this.api.run(request).subscribe({
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

  onPerformanceSubmit(observations: PostPerformanceObservation[]): void {
    if (!this.jobId) return;
    this.error = null;
    this.api.ingestPerformance(this.jobId, { observations }).subscribe({
      next: () => {},
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Ingest failed';
      },
    });
  }

  onReviseSubmit(request: ReviseMarketingTeamRequest): void {
    if (!this.jobId) return;
    this.loading = true;
    this.error = null;
    this.api.revise(this.jobId, request).subscribe({
      next: () => {
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Revise failed';
        this.loading = false;
      },
    });
  }
}
