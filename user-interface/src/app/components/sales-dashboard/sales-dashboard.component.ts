import { Component } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { TeamAssistantChatComponent } from '../team-assistant-chat/team-assistant-chat.component';

@Component({
  selector: 'app-sales-dashboard',
  standalone: true,
  imports: [
    MatIconModule,
    MatButtonModule,
    TeamAssistantChatComponent,
  ],
  templateUrl: './sales-dashboard.component.html',
  styleUrl: './sales-dashboard.component.scss',
})
export class SalesDashboardComponent {
}
