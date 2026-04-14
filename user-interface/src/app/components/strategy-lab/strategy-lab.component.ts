import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { CommonModule, DecimalPipe, DatePipe, CurrencyPipe, JsonPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTableModule } from '@angular/material/table';
import { MatSortModule } from '@angular/material/sort';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { Subscription, timer, switchMap, takeWhile } from 'rxjs';

import { InvestmentApiService } from '../../services/investment-api.service';
import type {
  StrategyLabRecord,
  StrategyLabResultsResponse,
  StrategyLabRunStatus,
  StrategyLabStreamEvent,
  StrategyLabPhase,
  TradeRecord,
} from '../../models';

type FilterMode = 'all' | 'winning' | 'losing';

const PHASE_LABELS: Record<string, string> = {
  ideating: 'Ideating strategy…',
  fetching_data: 'Fetching market data…',
  backtesting: 'Running backtest…',
  analyzing: 'Analyzing results…',
  complete: 'Complete',
};

@Component({
  selector: 'app-strategy-lab',
  standalone: true,
  imports: [
    CommonModule,
    DecimalPipe,
    DatePipe,
    CurrencyPipe,
    JsonPipe,
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatProgressBarModule,
    MatChipsModule,
    MatTooltipModule,
    MatDividerModule,
    MatButtonToggleModule,
    MatExpansionModule,
    MatTableModule,
    MatSortModule,
    MatPaginatorModule,
  ],
  templateUrl: './strategy-lab.component.html',
  styleUrl: './strategy-lab.component.scss',
})
export class StrategyLabComponent implements OnInit, OnDestroy {
  private readonly api = inject(InvestmentApiService);

  running = false;
  loading = false;
  clearingAll = false;
  error: string | null = null;
  /** Lab record id currently being deleted (disables actions on that card). */
  deletingLabRecordId: string | null = null;

  // User-configurable batch settings (mirror backend Field bounds).
  readonly BATCH_SIZE_MIN = 1;
  readonly BATCH_SIZE_MAX = 25;
  readonly BATCH_COUNT_MIN = 1;
  readonly BATCH_COUNT_MAX = 10;
  batchSize = 10;
  batchCount = 1;

  filter: FilterMode = 'all';
  results: StrategyLabResultsResponse | null = null;
  displayedItems: StrategyLabRecord[] = [];

  totalCount = 0;
  winningCount = 0;
  losingCount = 0;

  // Per-card trade ledger state
  tradeLedgerPages: Record<string, number> = {};       // lab_record_id → current page index
  readonly PAGE_SIZE = 20;
  readonly TRADE_COLUMNS = [
    'trade_num', 'entry_date', 'exit_date', 'symbol',
    'entry_price', 'exit_price', 'shares', 'return_pct',
    'net_pnl', 'cumulative_pnl', 'outcome',
  ];

  // Run progress tracking
  activeRunId: string | null = null;
  runStatus: StrategyLabRunStatus | null = null;
  private sseSub: Subscription | null = null;
  private pollSub: Subscription | null = null;

  ngOnInit(): void {
    this.loadResults();
    this.checkForActiveRun();
  }

  ngOnDestroy(): void {
    this.sseSub?.unsubscribe();
    this.pollSub?.unsubscribe();
  }

  // ---------------------------------------------------------------------------
  // Active run detection (for navigate-away-and-back)
  // ---------------------------------------------------------------------------

  private checkForActiveRun(): void {
    this.api.getActiveRuns().subscribe({
      next: (res) => {
        const active = res.runs.find((r) => r.status === 'running');
        if (active) {
          this.activeRunId = active.run_id;
          this.runStatus = active;
          this.running = true;
          this.connectToStream(active.run_id);
        }
      },
    });
  }

  // ---------------------------------------------------------------------------
  // SSE streaming + polling fallback
  // ---------------------------------------------------------------------------

  private connectToStream(runId: string): void {
    this.sseSub?.unsubscribe();
    this.sseSub = this.api.streamRunStatus(runId).subscribe({
      next: (event) => this.handleStreamEvent(event),
      error: () => this.fallbackToPolling(runId),
      complete: () => this.onRunComplete(),
    });
  }

  private handleStreamEvent(event: StrategyLabStreamEvent): void {
    if (event.type === 'snapshot' && this.runStatus) {
      // Merge snapshot fields into runStatus
      Object.assign(this.runStatus, {
        status: event['status'] ?? this.runStatus.status,
        completed_cycles: event['completed_cycles'] ?? this.runStatus.completed_cycles,
        skipped_cycles: event['skipped_cycles'] ?? this.runStatus.skipped_cycles,
        current_cycle: event['current_cycle'] ?? this.runStatus.current_cycle,
        completed_record_ids: event['completed_record_ids'] ?? this.runStatus.completed_record_ids,
        error: event['error'] ?? this.runStatus.error,
        batch_size: event['batch_size'] ?? this.runStatus.batch_size,
        batch_count: event['batch_count'] ?? this.runStatus.batch_count,
        completed_batches: event['completed_batches'] ?? this.runStatus.completed_batches,
        current_batch: event['current_batch'] ?? this.runStatus.current_batch,
      });
    }

    if (event.type === 'batch_start' && this.runStatus) {
      this.runStatus.current_batch = (event['batch_index'] as number) ?? this.runStatus.current_batch;
      this.runStatus.batch_count = (event['total_batches'] as number) ?? this.runStatus.batch_count;
      this.runStatus.completed_batches = (event['completed_batches'] as number) ?? this.runStatus.completed_batches;
    }

    if (event.type === 'batch_complete' && this.runStatus) {
      this.runStatus.completed_batches = (event['completed_batches'] as number) ?? this.runStatus.completed_batches;
      this.runStatus.current_batch = null;
    }

    if (event.type === 'progress' && this.runStatus) {
      this.runStatus.current_cycle = {
        cycle_index: (event['cycle_index'] as number) ?? 0,
        phase: (event['phase'] as StrategyLabPhase) ?? 'ideating',
        strategy: event['strategy'] as { asset_class: string; hypothesis: string } | undefined,
        metrics: event['metrics'] as Record<string, number> | undefined,
      };
    }

    if (event.type === 'cycle_complete' && this.runStatus) {
      this.runStatus.completed_cycles = (event['completed_cycles'] as number) ?? this.runStatus.completed_cycles + 1;
      this.runStatus.current_cycle = undefined;
      // Refresh completed cards
      this.loadResults();
    }

    if (event.type === 'cycle_skipped' && this.runStatus) {
      this.runStatus.skipped_cycles = (this.runStatus.skipped_cycles ?? 0) + 1;
      this.runStatus.current_cycle = undefined;
    }

    if (event.type === 'complete') {
      this.onRunComplete();
    }

    if (event.type === 'error') {
      this.error = (event['detail'] as string) || 'Run failed';
      this.onRunComplete();
    }
  }

  private onRunComplete(): void {
    this.running = false;
    this.activeRunId = null;
    this.runStatus = null;
    this.sseSub?.unsubscribe();
    this.sseSub = null;
    this.pollSub?.unsubscribe();
    this.pollSub = null;
    this.loadResults();
  }

  private fallbackToPolling(runId: string): void {
    this.pollSub?.unsubscribe();
    this.pollSub = timer(0, 5000).pipe(
      switchMap(() => this.api.getRunStatus(runId)),
      takeWhile((status) => status.status === 'running', true),
    ).subscribe({
      next: (status) => {
        this.runStatus = status;
        if (status.status !== 'running') {
          this.onRunComplete();
        }
      },
      error: () => {
        // Polling also failed — stop tracking
        this.onRunComplete();
      },
    });
  }

  // ---------------------------------------------------------------------------
  // Results
  // ---------------------------------------------------------------------------

  loadResults(): void {
    this.loading = true;
    this.error = null;
    this.api.getStrategyLabResults().subscribe({
      next: (res) => {
        this.results = res;
        this.totalCount = res.count;
        this.winningCount = res.winning_count;
        this.losingCount = res.losing_count;
        this.applyFilter();
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || err?.message || 'Failed to load results.';
        this.loading = false;
      },
    });
  }

  runNewStrategy(): void {
    const batchSize = this.clamp(this.batchSize, this.BATCH_SIZE_MIN, this.BATCH_SIZE_MAX);
    const batchCount = this.clamp(this.batchCount, this.BATCH_COUNT_MIN, this.BATCH_COUNT_MAX);
    // Reflect any clamping back into the form so the user sees what was sent.
    this.batchSize = batchSize;
    this.batchCount = batchCount;

    this.running = true;
    this.error = null;
    this.api.runStrategyLab({ batch_size: batchSize, batch_count: batchCount }).subscribe({
      next: (res) => {
        this.activeRunId = res.run_id;
        this.runStatus = {
          run_id: res.run_id,
          status: 'running',
          started_at: new Date().toISOString(),
          total_cycles: res.total_cycles,
          completed_cycles: 0,
          skipped_cycles: 0,
          completed_record_ids: [],
          batch_size: batchSize,
          batch_count: batchCount,
          completed_batches: 0,
          current_batch: batchCount > 1 ? 1 : null,
        };
        this.connectToStream(res.run_id);
      },
      error: (err) => {
        this.error = err?.error?.detail || err?.message || 'Strategy run failed.';
        this.running = false;
      },
    });
  }

  private clamp(value: number, min: number, max: number): number {
    const n = Number.isFinite(value) ? Math.floor(value) : min;
    return Math.max(min, Math.min(max, n));
  }

  /** Label for the run button — adapts to single- vs multi-batch mode. */
  runButtonLabel(): string {
    if (this.batchCount > 1) {
      const total = this.batchSize * this.batchCount;
      return `Run ${this.batchSize} \u00d7 ${this.batchCount} = ${total} strategies`;
    }
    return `Run ${this.batchSize} strateg${this.batchSize === 1 ? 'y' : 'ies'}`;
  }

  onFilterChange(mode: FilterMode): void {
    this.filter = mode;
    this.applyFilter();
  }

  private applyFilter(): void {
    const all = this.results?.items ?? [];
    if (this.filter === 'winning') {
      this.displayedItems = all.filter((r) => r.is_winning);
    } else if (this.filter === 'losing') {
      this.displayedItems = all.filter((r) => !r.is_winning);
    } else {
      this.displayedItems = all;
    }
  }

  returnColor(annualized: number): string {
    if (annualized > 8) return 'winning';
    if (annualized >= 0) return 'neutral';
    return 'losing';
  }

  phaseLabel(phase: string): string {
    return PHASE_LABELS[phase] ?? phase;
  }

  progressPercent(): number {
    if (!this.runStatus || this.runStatus.total_cycles === 0) return 0;
    return Math.round((this.runStatus.completed_cycles / this.runStatus.total_cycles) * 100);
  }

  // ---------------------------------------------------------------------------
  // Trade ledger helpers
  // ---------------------------------------------------------------------------

  getPageIndex(id: string): number {
    return this.tradeLedgerPages[id] ?? 0;
  }

  onPageChange(id: string, event: PageEvent): void {
    this.tradeLedgerPages[id] = event.pageIndex;
  }

  pagedTrades(record: StrategyLabRecord): TradeRecord[] {
    const page = this.getPageIndex(record.lab_record_id);
    const start = page * this.PAGE_SIZE;
    return record.backtest.trades.slice(start, start + this.PAGE_SIZE);
  }

  tradeCount(record: StrategyLabRecord): number {
    return record.backtest.trades.length;
  }

  winCount(record: StrategyLabRecord): number {
    return record.backtest.trades.filter((t) => t.outcome === 'win').length;
  }

  totalNetPnl(record: StrategyLabRecord): number {
    const trades = record.backtest.trades;
    return trades.length ? trades[trades.length - 1].cumulative_pnl : 0;
  }

  tradeReturnColor(t: TradeRecord): string {
    return t.outcome === 'win' ? 'win-cell' : 'loss-cell';
  }

  formatPrice(price: number): string {
    if (price >= 1000) return price.toFixed(0);
    if (price >= 1) return price.toFixed(2);
    return price.toFixed(4);
  }

  hasSignalBrief(record: StrategyLabRecord): boolean {
    return record.signal_intelligence_brief != null && Object.keys(record.signal_intelligence_brief).length > 0;
  }

  deleteRecord(record: StrategyLabRecord): void {
    const id = record.lab_record_id;
    const shortHyp = record.strategy.hypothesis.slice(0, 60) + (record.strategy.hypothesis.length > 60 ? '…' : '');
    if (
      !confirm(
        `Delete this strategy lab run?\n\n${shortHyp}\n\nThis removes the record, its backtest, and any paper-trading sessions for it. This cannot be undone.`
      )
    ) {
      return;
    }
    this.error = null;
    this.deletingLabRecordId = id;
    this.api.deleteStrategyLabRecord(id).subscribe({
      next: () => {
        this.deletingLabRecordId = null;
        this.loadResults();
      },
      error: (err) => {
        this.deletingLabRecordId = null;
        this.error = err?.error?.detail || err?.message || 'Failed to delete strategy.';
      },
    });
  }

  clearAllLabData(): void {
    if (
      !confirm(
        'Delete ALL strategy lab runs, lab strategies/backtests, and paper-trading sessions?\n\nThis cannot be undone.'
      )
    ) {
      return;
    }
    this.error = null;
    this.clearingAll = true;
    this.api.clearStrategyLabStorage().subscribe({
      next: () => {
        this.clearingAll = false;
        this.loadResults();
      },
      error: (err) => {
        this.clearingAll = false;
        this.error = err?.error?.detail || err?.message || 'Failed to clear strategy lab data.';
      },
    });
  }
}
