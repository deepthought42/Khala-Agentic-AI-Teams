import { Component, Input, Output, EventEmitter, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatListModule } from '@angular/material/list';
import { MatTooltipModule } from '@angular/material/tooltip';

import { InvestmentApiService } from '../../services/investment-api.service';
import {
  StrategySpec,
  CreateStrategyRequest,
  ValidateStrategyResponse,
} from '../../models';

@Component({
  selector: 'app-investment-strategy',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatChipsModule,
    MatDividerModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatExpansionModule,
    MatListModule,
    MatTooltipModule,
  ],
  templateUrl: './investment-strategy.component.html',
  styleUrl: './investment-strategy.component.scss',
})
export class InvestmentStrategyComponent implements OnInit {
  @Input() existingStrategy: StrategySpec | null = null;
  @Output() strategyCreated = new EventEmitter<StrategySpec>();
  @Output() validationCompleted = new EventEmitter<ValidateStrategyResponse>();

  private readonly api = inject(InvestmentApiService);
  private readonly fb = inject(FormBuilder);

  readonly assetClasses = ['equities', 'bonds', 'crypto', 'options', 'forex', 'commodities', 'multi_asset'];

  loading = false;
  validating = false;
  error: string | null = null;

  currentStrategy: StrategySpec | null = null;
  validationResult: ValidateStrategyResponse | null = null;

  form: FormGroup = this.fb.group({
    asset_class: ['equities', Validators.required],
    hypothesis: ['', Validators.required],
    signal_definition: ['', Validators.required],
    entry_rules: [''],
    exit_rules: [''],
    sizing_rules: [''],
    speculative: [false],
  });

  ngOnInit(): void {
    if (this.existingStrategy) {
      this.currentStrategy = this.existingStrategy;
      this.populateForm(this.existingStrategy);
    }
  }

  populateForm(strategy: StrategySpec): void {
    this.form.patchValue({
      asset_class: strategy.asset_class,
      hypothesis: strategy.hypothesis,
      signal_definition: strategy.signal_definition,
      entry_rules: strategy.entry_rules.join('\n'),
      exit_rules: strategy.exit_rules.join('\n'),
      sizing_rules: strategy.sizing_rules.join('\n'),
      speculative: strategy.speculative,
    });
  }

  async createStrategy(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.loading = true;
    this.error = null;

    const formValue = this.form.value;

    const request: CreateStrategyRequest = {
      authored_by: 'ui_user',
      asset_class: formValue.asset_class,
      hypothesis: formValue.hypothesis,
      signal_definition: formValue.signal_definition,
      entry_rules: this.splitLines(formValue.entry_rules),
      exit_rules: this.splitLines(formValue.exit_rules),
      sizing_rules: this.splitLines(formValue.sizing_rules),
      speculative: formValue.speculative,
    };

    this.api.createStrategy(request).subscribe({
      next: (response) => {
        this.loading = false;
        this.currentStrategy = response.strategy;
        this.strategyCreated.emit(response.strategy);
      },
      error: (err) => {
        this.loading = false;
        this.error = err.error?.detail || err.message || 'Failed to create strategy';
      },
    });
  }

  validateStrategy(): void {
    if (!this.currentStrategy) return;

    this.validating = true;
    this.validationResult = null;

    this.api.validateStrategy(this.currentStrategy.strategy_id).subscribe({
      next: (result) => {
        this.validating = false;
        this.validationResult = result;
        this.validationCompleted.emit(result);
      },
      error: (err) => {
        this.validating = false;
        this.error = err.error?.detail || err.message || 'Failed to validate strategy';
      },
    });
  }

  getCheckIcon(status: string): string {
    switch (status) {
      case 'pass':
        return 'check_circle';
      case 'warn':
        return 'warning';
      case 'fail':
        return 'cancel';
      default:
        return 'help';
    }
  }

  getCheckClass(status: string): string {
    return `check-${status}`;
  }

  private splitLines(text: string): string[] {
    if (!text) return [];
    return text.split('\n').map(s => s.trim()).filter(s => s);
  }
}
