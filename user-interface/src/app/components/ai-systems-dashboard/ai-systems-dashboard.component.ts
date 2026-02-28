import { Component, inject, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatExpansionModule } from '@angular/material/expansion';
import { Observable, Subscription, interval, switchMap, takeWhile } from 'rxjs';
import { AISystemsApiService } from '../../services/ai-systems-api.service';
import { HealthIndicatorComponent } from '../health-indicator/health-indicator.component';
import type {
  AISystemRequest,
  AISystemStatusResponse,
  AISystemJobSummary,
  AgentBlueprint,
  AISystemsHealthResponse,
} from '../../models';
import { AI_SYSTEM_PHASES } from '../../models';

type DashboardTab = 'build' | 'jobs' | 'blueprints';

@Component({
  selector: 'app-ai-systems-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTabsModule,
    MatIconModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    MatChipsModule,
    MatTableModule,
    MatExpansionModule,
    HealthIndicatorComponent,
  ],
  templateUrl: './ai-systems-dashboard.component.html',
  styleUrl: './ai-systems-dashboard.component.scss',
})
export class AISystemsDashboardComponent implements OnInit, OnDestroy {
  private readonly api = inject(AISystemsApiService);
  private readonly fb = inject(FormBuilder);
  
  private healthSub: Subscription | null = null;
  private jobPollSub: Subscription | null = null;

  selectedTabIndex = 0;
  activeTab: DashboardTab = 'build';

  healthStatus: AISystemsHealthResponse | null = null;
  healthLoading = false;
  healthError: string | null = null;

  buildForm: FormGroup;
  submitting = false;
  submitError: string | null = null;

  currentJobId: string | null = null;
  currentJobStatus: AISystemStatusResponse | null = null;

  jobs: AISystemJobSummary[] = [];
  jobsLoading = false;

  blueprintNames: string[] = [];
  blueprintsLoading = false;
  selectedBlueprint: AgentBlueprint | null = null;
  blueprintLoading = false;

  readonly phases = AI_SYSTEM_PHASES;

  readonly jobColumns = ['job_id', 'project_name', 'status', 'current_phase', 'progress'];

  constructor() {
    this.buildForm = this.fb.group({
      project_name: ['', Validators.required],
      spec_path: ['', Validators.required],
      output_dir: [''],
    });
  }

  ngOnInit(): void {
    this.checkHealth();
    this.loadJobs();
    this.loadBlueprintNames();
  }

  ngOnDestroy(): void {
    this.healthSub?.unsubscribe();
    this.jobPollSub?.unsubscribe();
  }

  checkHealth(): void {
    this.healthLoading = true;
    this.healthError = null;

    this.healthSub = this.api.healthCheck().subscribe({
      next: (res) => {
        this.healthStatus = res;
        this.healthLoading = false;
      },
      error: (err) => {
        this.healthError = err?.message ?? 'API unavailable';
        this.healthLoading = false;
      },
    });
  }

  onTabChange(index: number): void {
    this.selectedTabIndex = index;
    const tabs: DashboardTab[] = ['build', 'jobs', 'blueprints'];
    this.activeTab = tabs[index] || 'build';

    if (this.activeTab === 'jobs') {
      this.loadJobs();
    } else if (this.activeTab === 'blueprints') {
      this.loadBlueprintNames();
    }
  }

  onSubmitBuild(): void {
    if (this.buildForm.invalid) return;

    this.submitting = true;
    this.submitError = null;

    const request: AISystemRequest = {
      project_name: this.buildForm.value.project_name,
      spec_path: this.buildForm.value.spec_path,
      output_dir: this.buildForm.value.output_dir || undefined,
    };

    this.api.startBuild(request).subscribe({
      next: (res) => {
        this.currentJobId = res.job_id;
        this.submitting = false;
        this.startJobPolling(res.job_id);
      },
      error: (err) => {
        this.submitError = err?.error?.detail ?? err?.message ?? 'Failed to start build';
        this.submitting = false;
      },
    });
  }

  private startJobPolling(jobId: string): void {
    this.jobPollSub?.unsubscribe();

    this.jobPollSub = interval(2000)
      .pipe(
        switchMap(() => this.api.getJobStatus(jobId)),
        takeWhile((status) => status.status === 'running' || status.status === 'pending', true)
      )
      .subscribe({
        next: (status) => {
          this.currentJobStatus = status;
        },
        error: (err) => {
          console.error('Job polling error:', err);
        },
      });
  }

  loadJobs(): void {
    this.jobsLoading = true;
    this.api.listJobs().subscribe({
      next: (res) => {
        this.jobs = res.jobs;
        this.jobsLoading = false;
      },
      error: (err) => {
        console.error('Failed to load jobs:', err);
        this.jobsLoading = false;
      },
    });
  }

  loadBlueprintNames(): void {
    this.blueprintsLoading = true;
    this.api.listBlueprints().subscribe({
      next: (res) => {
        this.blueprintNames = res.blueprints;
        this.blueprintsLoading = false;
      },
      error: (err) => {
        console.error('Failed to load blueprints:', err);
        this.blueprintsLoading = false;
      },
    });
  }

  loadBlueprint(projectName: string): void {
    this.blueprintLoading = true;
    this.api.getBlueprint(projectName).subscribe({
      next: (blueprint) => {
        this.selectedBlueprint = blueprint;
        this.blueprintLoading = false;
      },
      error: (err) => {
        console.error('Failed to load blueprint:', err);
        this.blueprintLoading = false;
      },
    });
  }

  viewJobStatus(jobId: string): void {
    this.currentJobId = jobId;
    this.api.getJobStatus(jobId).subscribe({
      next: (status) => {
        this.currentJobStatus = status;
        this.selectedTabIndex = 0;
        this.activeTab = 'build';
        if (status.status === 'running' || status.status === 'pending') {
          this.startJobPolling(jobId);
        }
      },
      error: (err) => {
        console.error('Failed to load job status:', err);
      },
    });
  }

  clearCurrentJob(): void {
    this.currentJobId = null;
    this.currentJobStatus = null;
    this.jobPollSub?.unsubscribe();
    this.buildForm.reset({
      project_name: '',
      spec_path: '',
      output_dir: '',
    });
  }

  getPhaseLabel(phaseId: string): string {
    return this.phases.find(p => p.id === phaseId)?.label ?? phaseId;
  }

  isPhaseCompleted(phaseId: string): boolean {
    return this.currentJobStatus?.completed_phases?.includes(phaseId) ?? false;
  }

  isPhaseCurrent(phaseId: string): boolean {
    return this.currentJobStatus?.current_phase === phaseId;
  }

  get isJobActive(): boolean {
    return this.currentJobStatus?.status === 'running' || this.currentJobStatus?.status === 'pending';
  }

  get isJobComplete(): boolean {
    return this.currentJobStatus?.status === 'completed';
  }

  get isJobFailed(): boolean {
    return this.currentJobStatus?.status === 'failed';
  }
}
