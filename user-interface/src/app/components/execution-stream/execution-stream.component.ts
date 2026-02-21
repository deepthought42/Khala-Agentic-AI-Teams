import { Component, OnDestroy, OnInit } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';

@Component({
  selector: 'app-execution-stream',
  standalone: true,
  imports: [JsonPipe],
  templateUrl: './execution-stream.component.html',
  styleUrl: './execution-stream.component.scss',
})
export class ExecutionStreamComponent implements OnInit, OnDestroy {
  events: Record<string, unknown>[] = [];
  private sub: { unsubscribe: () => void } | null = null;

  constructor(private readonly api: SoftwareEngineeringApiService) {}

  ngOnInit(): void {
    this.sub = this.api.getExecutionStream().subscribe({
      next: (e) => this.events.push(e),
      error: () => {},
    }) as { unsubscribe: () => void };
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }
}
