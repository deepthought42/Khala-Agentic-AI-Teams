import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { StudioGridApiService } from '../../services/studio-grid-api.service';
import { ErrorMessageComponent } from '../../shared/error-message/error-message.component';
import type { AgentInfo } from '../../models';

@Component({
  selector: 'app-studio-grid-agents-registry',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatChipsModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    ErrorMessageComponent,
  ],
  templateUrl: './studio-grid-agents-registry.component.html',
  styleUrl: './studio-grid-agents-registry.component.scss',
})
export class StudioGridAgentsRegistryComponent implements OnInit {
  private readonly api = inject(StudioGridApiService);

  agents: AgentInfo[] = [];
  loading = false;
  error: string | null = null;
  searchTerm = '';

  get filteredAgents(): AgentInfo[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) return this.agents;
    return this.agents.filter(
      (a) =>
        a.agent_id.toLowerCase().includes(term) ||
        a.skills?.some((s) => s.toLowerCase().includes(term)) ||
        a.tools?.some((t) => t.toLowerCase().includes(term)) ||
        a.keywords?.some((k) => k.toLowerCase().includes(term)) ||
        a.actions?.some((ac) => ac.toLowerCase().includes(term))
    );
  }

  ngOnInit(): void {
    this.loadAgents();
  }

  loadAgents(): void {
    this.loading = true;
    this.error = null;
    this.api.listAgents().subscribe({
      next: (res) => {
        this.agents = res.agents;
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to load agents';
        this.loading = false;
      },
    });
  }

  shortId(agentId: string): string {
    return agentId.length > 20 ? agentId.slice(0, 20) + '…' : agentId;
  }

  totalCapabilities(agent: AgentInfo): number {
    return (
      (agent.skills?.length ?? 0) +
      (agent.tools?.length ?? 0) +
      (agent.keywords?.length ?? 0) +
      (agent.actions?.length ?? 0)
    );
  }
}
