import { Component, Input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';

@Component({
  selector: 'app-retry-failed',
  standalone: true,
  imports: [MatCardModule, MatButtonModule],
  templateUrl: './retry-failed.component.html',
  styleUrl: './retry-failed.component.scss',
})
export class RetryFailedComponent {
  @Input() jobId: string | null = null;
  @Input() hasFailedTasks = false;
  @Input() disabled = false;

  readonly retry = output<void>();
}
