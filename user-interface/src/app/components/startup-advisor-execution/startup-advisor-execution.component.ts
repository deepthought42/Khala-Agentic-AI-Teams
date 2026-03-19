import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';
import { StartupAdvisorFacadeService } from '../../services/startup-advisor-facade.service';
import type { StartupExecutionPlan } from '../../models';

@Component({
  selector: 'app-startup-advisor-execution',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    RouterLink,
  ],
  templateUrl: './startup-advisor-execution.component.html',
  styleUrl: './startup-advisor-execution.component.scss',
})
export class StartupAdvisorExecutionComponent implements OnInit {
  protected plan: StartupExecutionPlan | null = null;

  constructor(private readonly facade: StartupAdvisorFacadeService) {}

  ngOnInit(): void {
    this.plan = this.facade.buildExecutionPlan();
  }
}
