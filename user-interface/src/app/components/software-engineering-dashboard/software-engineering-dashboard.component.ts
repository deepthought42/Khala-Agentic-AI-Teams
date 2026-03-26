import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import { HealthIndicatorComponent } from '../health-indicator/health-indicator.component';
import { TeamAssistantChatComponent } from '../team-assistant-chat/team-assistant-chat.component';

@Component({
  selector: 'app-software-engineering-dashboard',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    HealthIndicatorComponent,
    TeamAssistantChatComponent,
  ],
  templateUrl: './software-engineering-dashboard.component.html',
  styleUrl: './software-engineering-dashboard.component.scss',
})
export class SoftwareEngineeringDashboardComponent {
  private readonly api = inject(SoftwareEngineeringApiService);

  healthCheck = (): ReturnType<SoftwareEngineeringApiService['health']> =>
    this.api.health();
}
