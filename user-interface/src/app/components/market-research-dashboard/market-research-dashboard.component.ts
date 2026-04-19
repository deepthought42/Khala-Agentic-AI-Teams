import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MarketResearchApiService } from '../../services/market-research-api.service';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TeamAssistantChatComponent } from '../team-assistant-chat/team-assistant-chat.component';
import { DashboardShellComponent } from '../../shared/dashboard-shell/dashboard-shell.component';

@Component({
  selector: 'app-market-research-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    DashboardShellComponent,
    MatButtonModule,
    MatIconModule,
    TeamAssistantChatComponent,
  ],
  templateUrl: './market-research-dashboard.component.html',
  styleUrl: './market-research-dashboard.component.scss',
})
export class MarketResearchDashboardComponent {
  private readonly api = inject(MarketResearchApiService);

  /** Last-launched result payload. Market Research is synchronous — the
   * upstream body is the ``TeamOutput`` returned inline by /market-research/run. */
  lastResult: Record<string, unknown> | null = null;
  /** Pretty-printed JSON for display; derived from ``lastResult``. */
  lastResultJson = '';

  healthCheck = (): ReturnType<MarketResearchApiService['health']> =>
    this.api.health();

  onWorkflowLaunched(event: {
    job_id: string | null;
    conversation_id: string;
    upstream_status: number;
    upstream_body: Record<string, unknown>;
  }): void {
    // Market Research returns its TeamOutput inline with no job_id. Surface
    // the body so the run isn't invisible to the user.
    this.lastResult = event.upstream_body;
    try {
      this.lastResultJson = JSON.stringify(event.upstream_body, null, 2);
    } catch {
      this.lastResultJson = String(event.upstream_body);
    }
  }

  clearResult(): void {
    this.lastResult = null;
    this.lastResultJson = '';
  }
}
