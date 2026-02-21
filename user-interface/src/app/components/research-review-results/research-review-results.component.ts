import { Component, Input } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatChipsModule } from '@angular/material/chips';
import type { ResearchAndReviewResponse } from '../../models';

/**
 * Displays the response from POST /research-and-review.
 */
@Component({
  selector: 'app-research-review-results',
  standalone: true,
  imports: [MatCardModule, MatExpansionModule, MatChipsModule],
  templateUrl: './research-review-results.component.html',
  styleUrl: './research-review-results.component.scss',
})
export class ResearchReviewResultsComponent {
  /** Response data to display. */
  @Input() data: ResearchAndReviewResponse | null = null;
}
