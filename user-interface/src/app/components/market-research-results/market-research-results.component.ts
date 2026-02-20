import { Component, Input } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import type { TeamOutput } from '../../models';

@Component({
  selector: 'app-market-research-results',
  standalone: true,
  imports: [MatCardModule, MatExpansionModule],
  templateUrl: './market-research-results.component.html',
  styleUrl: './market-research-results.component.scss',
})
export class MarketResearchResultsComponent {
  @Input() data: TeamOutput | null = null;
}
