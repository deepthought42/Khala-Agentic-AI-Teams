import { Component, OnDestroy, OnInit, inject } from '@angular/core';
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
  private readonly api = inject(SoftwareEngineeringApiService);

  events: Record<string, unknown>[] = [];
  private sub: { unsubscribe: () => void } | null = null;

  ngOnInit(): void {
    this.sub = this.api.getExecutionStream().subscribe({
      next: (e) => this.events.push(e),
      // eslint-disable-next-line @typescript-eslint/no-empty-function
      error: () => {},
    }) as { unsubscribe: () => void };
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }
}
