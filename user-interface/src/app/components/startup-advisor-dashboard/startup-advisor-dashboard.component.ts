import { Component } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-startup-advisor-dashboard',
  standalone: true,
  imports: [
    MatCardModule,
    MatIconModule,
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
  ],
  templateUrl: './startup-advisor-dashboard.component.html',
  styleUrl: './startup-advisor-dashboard.component.scss',
})
export class StartupAdvisorDashboardComponent {}
