import { Component, Input } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import type { FullPipelineResponse } from '../../models';

/**
 * Displays the response from POST /full-pipeline.
 */
@Component({
  selector: 'app-full-pipeline-results',
  standalone: true,
  imports: [MatCardModule, MatChipsModule],
  templateUrl: './full-pipeline-results.component.html',
  styleUrl: './full-pipeline-results.component.scss',
})
export class FullPipelineResultsComponent {
  @Input() data: FullPipelineResponse | null = null;
}
