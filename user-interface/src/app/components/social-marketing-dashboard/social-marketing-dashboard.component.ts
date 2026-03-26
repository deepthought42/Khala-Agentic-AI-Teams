import { Component } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TeamAssistantChatComponent } from '../team-assistant-chat/team-assistant-chat.component';

@Component({
  selector: 'app-social-marketing-dashboard',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    TeamAssistantChatComponent,
  ],
  templateUrl: './social-marketing-dashboard.component.html',
  styleUrl: './social-marketing-dashboard.component.scss',
})
export class SocialMarketingDashboardComponent {
}
