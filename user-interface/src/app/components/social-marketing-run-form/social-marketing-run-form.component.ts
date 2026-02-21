import { Component, output } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatCardModule } from '@angular/material/card';
import type { RunMarketingTeamRequest } from '../../models';

@Component({
  selector: 'app-social-marketing-run-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatCheckboxModule,
    MatButtonModule,
  ],
  templateUrl: './social-marketing-run-form.component.html',
  styleUrl: './social-marketing-run-form.component.scss',
})
export class SocialMarketingRunFormComponent {
  readonly submitRequest = output<RunMarketingTeamRequest>();

  form: FormGroup;

  constructor(private readonly fb: FormBuilder) {
    this.form = this.fb.nonNullable.group({
      brand_guidelines_path: ['', Validators.required],
      brand_objectives_path: ['', Validators.required],
      llm_model_name: ['', Validators.required],
      brand_name: ['Brand'],
      target_audience: ['general audience'],
      goals: ['engagement, follower growth'],
      voice_and_tone: ['professional, clear, and human'],
      cadence_posts_per_day: [2, [Validators.required, Validators.min(1)]],
      duration_days: [14, [Validators.required, Validators.min(1)]],
      human_approved_for_testing: [false],
      human_feedback: [''],
    });
  }

  onSubmit(): void {
    if (this.form.valid) {
      const v = this.form.getRawValue();
      const goals = typeof v.goals === 'string'
        ? v.goals.split(',').map((s: string) => s.trim()).filter(Boolean)
        : v.goals;
      this.submitRequest.emit({
        brand_guidelines_path: v.brand_guidelines_path,
        brand_objectives_path: v.brand_objectives_path,
        llm_model_name: v.llm_model_name,
        brand_name: v.brand_name,
        target_audience: v.target_audience,
        goals: goals.length ? goals : ['engagement', 'follower growth'],
        voice_and_tone: v.voice_and_tone,
        cadence_posts_per_day: v.cadence_posts_per_day,
        duration_days: v.duration_days,
        human_approved_for_testing: v.human_approved_for_testing,
        human_feedback: v.human_feedback || '',
      });
    }
  }
}
