import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { Router, RouterLink } from '@angular/router';
import { StartupAdvisorFacadeService } from '../../services/startup-advisor-facade.service';
import { LoadingSpinnerComponent } from '../../shared/loading-spinner/loading-spinner.component';
import { ErrorMessageComponent } from '../../shared/error-message/error-message.component';
import type { StartupAdvisorRecommendation } from '../../models';

@Component({
  selector: 'app-startup-advisor-recommendations',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    RouterLink,
    LoadingSpinnerComponent,
    ErrorMessageComponent,
  ],
  templateUrl: './startup-advisor-recommendations.component.html',
  styleUrl: './startup-advisor-recommendations.component.scss',
})
export class StartupAdvisorRecommendationsComponent implements OnInit {
  protected recommendations: StartupAdvisorRecommendation[] = [];
  protected loading = false;
  protected error: string | null = null;

  constructor(
    private readonly facade: StartupAdvisorFacadeService,
    private readonly router: Router,
  ) {}

  ngOnInit(): void {
    const intake = this.facade.intakeSnapshot;
    if (!intake) {
      return;
    }
    this.fetchRecommendations(false);
  }

  protected fetchRecommendations(forceRefresh: boolean): void {
    const intake = this.facade.intakeSnapshot;
    if (!intake) {
      return;
    }

    this.loading = true;
    this.error = null;
    this.facade.getRecommendations(intake, forceRefresh).subscribe({
      next: (recommendations) => {
        this.recommendations = recommendations;
        this.loading = false;
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail ?? err?.message ?? 'Unable to load advisor recommendations.';
      },
    });
  }

  protected proceedToExecution(): void {
    this.router.navigate(['/startup-advisor/execution']);
  }

  protected get hasIntake(): boolean {
    return !!this.facade.intakeSnapshot;
  }
}
