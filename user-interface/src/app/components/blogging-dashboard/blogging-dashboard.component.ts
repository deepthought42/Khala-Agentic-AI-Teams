import { Component, inject } from '@angular/core';
import { MatTabsModule } from '@angular/material/tabs';
import { BloggingApiService } from '../../services/blogging-api.service';
import { LoadingSpinnerComponent } from '../../shared/loading-spinner/loading-spinner.component';
import { ErrorMessageComponent } from '../../shared/error-message/error-message.component';
import { HealthIndicatorComponent } from '../health-indicator/health-indicator.component';
import { ResearchReviewFormComponent } from '../research-review-form/research-review-form.component';
import { ResearchReviewResultsComponent } from '../research-review-results/research-review-results.component';
import { FullPipelineFormComponent } from '../full-pipeline-form/full-pipeline-form.component';
import { FullPipelineResultsComponent } from '../full-pipeline-results/full-pipeline-results.component';
import type {
  ResearchAndReviewRequest,
  ResearchAndReviewResponse,
  FullPipelineRequest,
  FullPipelineResponse,
} from '../../models';

/**
 * Blogging API dashboard: research-and-review and full-pipeline forms and results.
 */
@Component({
  selector: 'app-blogging-dashboard',
  standalone: true,
  imports: [
    MatTabsModule,
    LoadingSpinnerComponent,
    ErrorMessageComponent,
    HealthIndicatorComponent,
    ResearchReviewFormComponent,
    ResearchReviewResultsComponent,
    FullPipelineFormComponent,
    FullPipelineResultsComponent,
  ],
  templateUrl: './blogging-dashboard.component.html',
  styleUrl: './blogging-dashboard.component.scss',
})
export class BloggingDashboardComponent {
  private readonly api = inject(BloggingApiService);

  loading = false;
  error: string | null = null;
  researchReviewResult: ResearchAndReviewResponse | null = null;
  fullPipelineResult: FullPipelineResponse | null = null;

  /** Health check for the indicator. */
  healthCheck = (): ReturnType<BloggingApiService['health']> => this.api.health();

  onResearchReviewSubmit(request: ResearchAndReviewRequest): void {
    this.loading = true;
    this.error = null;
    this.researchReviewResult = null;
    this.api.researchAndReview(request).subscribe({
      next: (res) => {
        this.researchReviewResult = res;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Request failed';
        this.loading = false;
      },
    });
  }

  onFullPipelineSubmit(request: FullPipelineRequest): void {
    this.loading = true;
    this.error = null;
    this.fullPipelineResult = null;
    this.api.fullPipeline(request).subscribe({
      next: (res) => {
        this.fullPipelineResult = res;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Request failed';
        this.loading = false;
      },
    });
  }
}
