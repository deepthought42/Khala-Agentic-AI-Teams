import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatDividerModule } from '@angular/material/divider';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { StudioGridApiService } from '../../services/studio-grid-api.service';
import { LoadingSpinnerComponent } from '../../shared/loading-spinner/loading-spinner.component';
import { ErrorMessageComponent } from '../../shared/error-message/error-message.component';
import type { StartRunResponse, RunStatus, Decision } from '../../models';

const PHASES = ['INTAKE', 'DISCOVERY', 'IA', 'WIREFRAMES', 'SYSTEM', 'HIFI', 'ASSETS', 'HANDOFF', 'DONE'];

@Component({
  selector: 'app-studio-grid-run-panel',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatChipsModule,
    MatIconModule,
    MatDividerModule,
    MatExpansionModule,
    MatProgressBarModule,
    MatTooltipModule,
    LoadingSpinnerComponent,
    ErrorMessageComponent,
  ],
  templateUrl: './studio-grid-run-panel.component.html',
  styleUrl: './studio-grid-run-panel.component.scss',
})
export class StudioGridRunPanelComponent {
  private readonly api = inject(StudioGridApiService);

  readonly phases = PHASES;

  // Form fields
  projectName = '';
  brief = '';
  targetUsers = '';
  constraints = '';
  stylePreferences = '';

  // Async state
  loading = false;
  error: string | null = null;

  // Run state
  run: StartRunResponse | RunStatus | null = null;
  decisions: Decision[] = [];

  // Resolve state
  resolvingDecisionId: string | null = null;
  resolveError: string | null = null;

  get currentPhaseIndex(): number {
    if (!this.run) return -1;
    return PHASES.indexOf(this.run.phase);
  }

  get openDecisions(): Decision[] {
    return this.decisions.filter((d) => d.status === 'OPEN');
  }

  get resolvedDecisions(): Decision[] {
    return this.decisions.filter((d) => d.status === 'CHOSEN');
  }

  get progressPercent(): number {
    const idx = this.currentPhaseIndex;
    if (idx < 0) return 0;
    return Math.round((idx / (PHASES.length - 1)) * 100);
  }

  onStartRun(): void {
    this.loading = true;
    this.error = null;
    this.run = null;
    this.decisions = [];

    const intake: Record<string, unknown> = {
      brief: this.brief,
      target_users: this.targetUsers,
      constraints: this.constraints,
      style_preferences: this.stylePreferences,
    };

    this.api.startRun({ project_name: this.projectName, intake }).subscribe({
      next: (res) => {
        this.run = res;
        this.loading = false;
        this.loadDecisions(res.run_id);
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to start run';
        this.loading = false;
      },
    });
  }

  onRefreshStatus(): void {
    if (!this.run) return;
    this.api.getRunStatus(this.run.run_id).subscribe({
      next: (status) => {
        this.run = status;
        this.loadDecisions(status.run_id);
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to refresh status';
      },
    });
  }

  private loadDecisions(runId: string): void {
    this.api.listDecisions(runId).subscribe({
      next: (res) => {
        this.decisions = res.decisions;
      },
      error: () => {
        // decisions are optional — ignore errors
      },
    });
  }

  onResolveDecision(decisionId: string, optionKey: string): void {
    this.resolvingDecisionId = decisionId;
    this.resolveError = null;
    this.api.resolveDecision(decisionId, optionKey).subscribe({
      next: (updated) => {
        this.decisions = this.decisions.map((d) =>
          d.decision_id === decisionId ? updated : d
        );
        this.resolvingDecisionId = null;
      },
      error: (err) => {
        this.resolveError = err?.error?.detail ?? err?.message ?? 'Failed to resolve decision';
        this.resolvingDecisionId = null;
      },
    });
  }

  onNewRun(): void {
    this.run = null;
    this.decisions = [];
    this.error = null;
    this.resolveError = null;
    this.resolvingDecisionId = null;
  }

  get runUpdatedAt(): string | undefined {
    if (!this.run) return undefined;
    return 'updated_at' in this.run ? this.run.updated_at : undefined;
  }

  get runContractVersion(): number | undefined {
    if (!this.run) return undefined;
    return 'contract_version' in this.run ? this.run.contract_version : undefined;
  }

  phaseStatus(phase: string): 'done' | 'active' | 'pending' {
    const idx = PHASES.indexOf(phase);
    if (idx < this.currentPhaseIndex) return 'done';
    if (idx === this.currentPhaseIndex) return 'active';
    return 'pending';
  }
}
