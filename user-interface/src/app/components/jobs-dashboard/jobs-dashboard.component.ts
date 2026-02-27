import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Subscription, forkJoin, of, timer } from 'rxjs';
import { switchMap, catchError } from 'rxjs/operators';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import type { RunningJobSummary, JobStatusResponse, PlanningV2StatusResponse, ProductAnalysisStatusResponse, TeamProgressEntry } from '../../models';

/** Per-team status for dashboard display. */
interface TeamStatus {
  teamId: string;
  label: string;
  icon: string;
  phase: string;
  phaseLabel: string;
  isActive: boolean;
}

/** Extended job info with detailed status for dashboard display. */
interface DashboardJob {
  summary: RunningJobSummary;
  progress?: number;
  statusText?: string;
  currentPhase?: string;
  waitingForAnswers?: boolean;
  teamStatuses?: TeamStatus[];
}

/** Job type metadata for display. */
interface JobTypeInfo {
  label: string;
  icon: string;
  route: string;
  tabIndex?: number;
}

const JOB_TYPE_INFO: Record<string, JobTypeInfo> = {
  'run_team': { label: 'Run Team', icon: 'groups', route: '/software-engineering', tabIndex: 0 },
  'planning_v2': { label: 'Planning V2', icon: 'architecture', route: '/software-engineering/planning-v2' },
  'backend_code_v2': { label: 'Backend Code V2', icon: 'dns', route: '/software-engineering', tabIndex: 4 },
  'frontend_code_v2': { label: 'Frontend Code V2', icon: 'web', route: '/software-engineering', tabIndex: 5 },
  'product_analysis': { label: 'Product Analysis', icon: 'analytics', route: '/software-engineering', tabIndex: 1 },
};

const TEAM_DISPLAY_INFO: Record<string, { label: string; icon: string }> = {
  'planning': { label: 'Planning', icon: 'architecture' },
  'backend-code-v2': { label: 'Backend', icon: 'dns' },
  'frontend-code-v2': { label: 'Frontend', icon: 'web' },
  'backend': { label: 'Backend', icon: 'dns' },
  'frontend': { label: 'Frontend', icon: 'web' },
  'devops': { label: 'DevOps', icon: 'build' },
  'product_analysis': { label: 'Analysis', icon: 'analytics' },
};

const PHASE_DISPLAY: Record<string, string> = {
  'setup': 'Setup',
  'planning': 'Planning',
  'execution': 'Execution',
  'review': 'Review',
  'documentation': 'Docs',
  'deliver': 'Deliver',
  'completed': 'Done',
  'coding': 'Coding',
  'code_review': 'Code Review',
  'qa_testing': 'QA',
  'security_testing': 'Security',
  'problem_solving': 'Fixing',
};

@Component({
  selector: 'app-jobs-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatProgressBarModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
  ],
  templateUrl: './jobs-dashboard.component.html',
  styleUrl: './jobs-dashboard.component.scss',
})
export class JobsDashboardComponent implements OnInit, OnDestroy {
  private readonly api = inject(SoftwareEngineeringApiService);
  private readonly router = inject(Router);

  jobs: DashboardJob[] = [];
  loading = true;
  error: string | null = null;
  lastUpdated: Date | null = null;

  private pollSub: Subscription | null = null;
  private readonly POLL_INTERVAL = 10000;

  ngOnInit(): void {
    this.startPolling();
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  private startPolling(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = timer(0, this.POLL_INTERVAL)
      .pipe(
        switchMap(() => this.api.getRunningJobs()),
        switchMap((response) => {
          const jobs = response.jobs;
          if (jobs.length === 0) {
            return of([]);
          }
          const detailRequests = jobs.map((job) => this.fetchJobDetails(job));
          return forkJoin(detailRequests);
        }),
        catchError((err) => {
          this.error = err?.message ?? 'Failed to fetch jobs';
          this.loading = false;
          return of([]);
        })
      )
      .subscribe({
        next: (dashboardJobs) => {
          this.jobs = dashboardJobs;
          this.loading = false;
          this.error = null;
          this.lastUpdated = new Date();
        },
      });
  }

  private fetchJobDetails(summary: RunningJobSummary) {
    const jobType = summary.job_type;

    if (jobType === 'planning_v2') {
      return this.api.getPlanningV2Status(summary.job_id).pipe(
        switchMap((status: PlanningV2StatusResponse) => of(this.toDashboardJob(summary, {
          progress: status.progress,
          currentPhase: status.current_phase,
          waitingForAnswers: status.waiting_for_answers,
          teamStatuses: this.buildTeamStatuses({ 'planning': { current_phase: status.current_phase, progress: status.progress } }),
        }))),
        catchError(() => of(this.toDashboardJob(summary)))
      );
    }

    if (jobType === 'product_analysis') {
      return this.api.getProductAnalysisStatus(summary.job_id).pipe(
        switchMap((status: ProductAnalysisStatusResponse) => of(this.toDashboardJob(summary, {
          progress: status.progress,
          statusText: status.status_text,
          currentPhase: status.current_phase,
          waitingForAnswers: status.waiting_for_answers,
          teamStatuses: this.buildTeamStatuses({ 'product_analysis': { current_phase: status.current_phase, progress: status.progress } }),
        }))),
        catchError(() => of(this.toDashboardJob(summary)))
      );
    }

    if (jobType === 'backend_code_v2') {
      return this.api.getBackendCodeV2Status(summary.job_id).pipe(
        switchMap((status) => of(this.toDashboardJob(summary, {
          progress: status.progress,
          currentPhase: status.current_phase,
          teamStatuses: this.buildTeamStatuses({ 'backend-code-v2': { current_phase: status.current_phase, progress: status.progress } }),
        }))),
        catchError(() => of(this.toDashboardJob(summary)))
      );
    }

    if (jobType === 'frontend_code_v2') {
      return this.api.getFrontendCodeV2Status(summary.job_id).pipe(
        switchMap((status) => of(this.toDashboardJob(summary, {
          progress: status.progress,
          currentPhase: status.current_phase,
          teamStatuses: this.buildTeamStatuses({ 'frontend-code-v2': { current_phase: status.current_phase, progress: status.progress } }),
        }))),
        catchError(() => of(this.toDashboardJob(summary)))
      );
    }

    return this.api.getJobStatus(summary.job_id).pipe(
      switchMap((status: JobStatusResponse) => of(this.toDashboardJob(summary, {
        progress: status.progress,
        statusText: status.status_text,
        currentPhase: status.phase,
        waitingForAnswers: status.waiting_for_answers,
        teamStatuses: this.buildTeamStatuses(status.team_progress),
      }))),
      catchError(() => of(this.toDashboardJob(summary)))
    );
  }

  private buildTeamStatuses(teamProgress?: Record<string, TeamProgressEntry>): TeamStatus[] {
    if (!teamProgress) return [];
    return Object.entries(teamProgress)
      .filter(([, entry]) => entry.current_phase)
      .map(([teamId, entry]) => {
        const displayInfo = TEAM_DISPLAY_INFO[teamId] ?? { label: teamId, icon: 'smart_toy' };
        const phase = entry.current_phase ?? '';
        const phaseLabel = PHASE_DISPLAY[phase] ?? phase.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
        return {
          teamId,
          label: displayInfo.label,
          icon: displayInfo.icon,
          phase,
          phaseLabel,
          isActive: phase !== 'completed' && phase !== '',
        };
      });
  }

  private toDashboardJob(
    summary: RunningJobSummary,
    details?: Partial<Pick<DashboardJob, 'progress' | 'statusText' | 'currentPhase' | 'waitingForAnswers' | 'teamStatuses'>>
  ): DashboardJob {
    return {
      summary,
      progress: details?.progress,
      statusText: details?.statusText,
      currentPhase: details?.currentPhase,
      waitingForAnswers: details?.waitingForAnswers,
      teamStatuses: details?.teamStatuses,
    };
  }

  refresh(): void {
    this.loading = true;
    this.startPolling();
  }

  getJobTypeInfo(jobType: string): JobTypeInfo {
    return JOB_TYPE_INFO[jobType] ?? { label: jobType, icon: 'work', route: '/software-engineering' };
  }

  getRepoName(repoPath?: string): string {
    if (!repoPath) return 'Unknown';
    const parts = repoPath.split('/');
    return parts[parts.length - 1] || repoPath;
  }

  getStatusClass(job: DashboardJob): string {
    if (job.waitingForAnswers) return 'status-waiting';
    switch (job.summary.status) {
      case 'running': return 'status-running';
      case 'completed': return 'status-completed';
      case 'failed': return 'status-failed';
      default: return 'status-pending';
    }
  }

  getStatusLabel(job: DashboardJob): string {
    if (job.waitingForAnswers) return 'Waiting';
    return job.summary.status.charAt(0).toUpperCase() + job.summary.status.slice(1);
  }

  getTimeAgo(createdAt?: string): string {
    if (!createdAt) return '';
    const created = new Date(createdAt);
    const now = new Date();
    const diffMs = now.getTime() - created.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  }

  getActivityText(job: DashboardJob): string {
    if (job.waitingForAnswers) return 'Waiting for answers';
    if (job.statusText) return job.statusText;
    if (job.currentPhase) {
      return job.currentPhase.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    }
    return '';
  }

  truncateJobId(jobId: string): string {
    if (jobId.length <= 12) return jobId;
    return jobId.substring(0, 8) + '...';
  }

  navigateToJob(job: DashboardJob): void {
    const info = this.getJobTypeInfo(job.summary.job_type);
    const queryParams: Record<string, string | number> = { jobId: job.summary.job_id };
    if (info.tabIndex !== undefined) {
      queryParams['tab'] = info.tabIndex;
    }
    this.router.navigate([info.route], { queryParams });
  }

  trackByJobId(_index: number, job: DashboardJob): string {
    return job.summary.job_id;
  }

  getPhaseColorClass(phase: string): string {
    switch (phase) {
      case 'setup':
      case 'planning':
        return 'phase-planning';
      case 'execution':
      case 'coding':
        return 'phase-execution';
      case 'review':
      case 'code_review':
      case 'qa_testing':
      case 'security_testing':
        return 'phase-review';
      case 'documentation':
        return 'phase-docs';
      case 'deliver':
      case 'completed':
        return 'phase-completed';
      case 'problem_solving':
        return 'phase-fixing';
      default:
        return 'phase-default';
    }
  }

  trackByTeamId(_index: number, team: TeamStatus): string {
    return team.teamId;
  }
}
