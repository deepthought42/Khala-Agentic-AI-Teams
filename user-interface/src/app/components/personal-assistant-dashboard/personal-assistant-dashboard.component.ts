import { Component, inject } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { PersonalAssistantApiService } from '../../services/personal-assistant-api.service';
import { TeamAssistantChatComponent } from '../team-assistant-chat/team-assistant-chat.component';
import { HealthIndicatorComponent } from '../health-indicator/health-indicator.component';

/**
 * Personal Assistant Dashboard - main container with tabbed interface.
 */
@Component({
  selector: 'app-personal-assistant-dashboard',
  standalone: true,
  imports: [
    MatIconModule,
    MatButtonModule,
    HealthIndicatorComponent,
    TeamAssistantChatComponent,
  ],
  templateUrl: './personal-assistant-dashboard.component.html',
  styleUrl: './personal-assistant-dashboard.component.scss',
})
export class PersonalAssistantDashboardComponent {
  private readonly api = inject(PersonalAssistantApiService);

  healthCheck = (): ReturnType<PersonalAssistantApiService['health']> => this.api.health();
}
