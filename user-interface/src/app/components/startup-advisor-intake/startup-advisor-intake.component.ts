import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { Router } from '@angular/router';
import { StartupAdvisorFacadeService } from '../../services/startup-advisor-facade.service';
import type { FocusArea, StartupAdvisorIntake, StartupStage } from '../../models';

@Component({
  selector: 'app-startup-advisor-intake',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
  ],
  templateUrl: './startup-advisor-intake.component.html',
  styleUrl: './startup-advisor-intake.component.scss',
})
export class StartupAdvisorIntakeComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly facade = inject(StartupAdvisorFacadeService);

  private readonly fb = inject(FormBuilder);

  protected readonly stageOptions: { value: StartupStage; label: string }[] = [
    { value: 'idea', label: 'Idea validation' },
    { value: 'mvp', label: 'MVP build' },
    { value: 'early-revenue', label: 'Early revenue' },
    { value: 'growth', label: 'Growth stage' },
    { value: 'scale', label: 'Scaling' },
  ];

  protected readonly focusAreaOptions: { key: FocusArea; label: string }[] = [
    { key: 'customer_discovery', label: 'Customer discovery' },
    { key: 'product_strategy', label: 'Product strategy' },
    { key: 'growth_gtm', label: 'Growth and GTM' },
    { key: 'fundraising_finance', label: 'Fundraising and finance' },
    { key: 'operations_legal', label: 'Operations and legal' },
    { key: 'founder_coaching', label: 'Founder coaching' },
  ];

  protected readonly form = this.fb.nonNullable.group({
    startupName: ['', [Validators.required, Validators.maxLength(80)]],
    founderRole: ['', [Validators.required, Validators.maxLength(80)]],
    stage: ['idea' as StartupStage, Validators.required],
    primaryGoal: ['', [Validators.required, Validators.maxLength(200)]],
    currentChallenge: ['', [Validators.required, Validators.maxLength(800)]],
    targetHorizonWeeks: [12, [Validators.required, Validators.min(4), Validators.max(52)]],
    teamSize: [3, [Validators.required, Validators.min(1), Validators.max(500)]],
    budgetBand: ['<$10k / month', Validators.required],
    focusAreas: [[] as FocusArea[], Validators.required],
  });

  ngOnInit(): void {
    const intake = this.facade.intakeSnapshot;
    if (intake) {
      this.form.patchValue(intake);
    }
  }

  protected toggleFocusArea(area: FocusArea, enabled: boolean): void {
    const current = this.form.controls.focusAreas.value;
    const next = enabled ? [...new Set([...current, area])] : current.filter((item) => item !== area);
    this.form.controls.focusAreas.setValue(next);
    this.form.controls.focusAreas.markAsTouched();
  }

  protected isFocusAreaSelected(area: FocusArea): boolean {
    return this.form.controls.focusAreas.value.includes(area);
  }

  protected continueToRecommendations(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const intake: StartupAdvisorIntake = this.form.getRawValue();
    this.facade.setIntake(intake);
    this.router.navigate(['/startup-advisor/recommendations']);
  }
}
