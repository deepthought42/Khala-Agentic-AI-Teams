import { Component, Input } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

/**
 * Reusable inline error message display.
 */
@Component({
  selector: 'app-error-message',
  standalone: true,
  imports: [MatCardModule, MatIconModule],
  templateUrl: './error-message.component.html',
  styleUrl: './error-message.component.scss',
})
export class ErrorMessageComponent {
  /** Error message to display. */
  @Input() message = 'An error occurred.';

  /** Optional title. Default "Error". */
  @Input() title = 'Error';
}
