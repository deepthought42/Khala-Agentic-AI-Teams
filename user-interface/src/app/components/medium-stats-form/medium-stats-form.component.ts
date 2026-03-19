import { Component, output } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import type { MediumStatsRequest } from '../../models';

/**
 * Form for POST /medium-stats-async. Optional fields override server env when set.
 */
@Component({
  selector: 'app-medium-stats-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSlideToggleModule,
    MatButtonModule,
  ],
  templateUrl: './medium-stats-form.component.html',
  styleUrl: './medium-stats-form.component.scss',
})
export class MediumStatsFormComponent {
  readonly submitRequest = output<MediumStatsRequest>();

  readonly form: FormGroup;

  constructor(private readonly fb: FormBuilder) {
    this.form = this.fb.nonNullable.group({
      headless: [true],
      timeout_ms: [90_000, [Validators.required, Validators.min(5000), Validators.max(600_000)]],
      max_posts: [null as number | null],
      storage_state_path: [''],
      medium_email: [''],
      medium_password: [''],
    });
  }

  onSubmit(): void {
    if (this.form.invalid) return;
    const v = this.form.getRawValue() as {
      headless: boolean;
      timeout_ms: number;
      max_posts: number | null;
      storage_state_path: string;
      medium_email: string;
      medium_password: string;
    };
    const payload: MediumStatsRequest = {
      headless: v.headless,
      timeout_ms: v.timeout_ms,
    };
    if (v.max_posts != null && v.max_posts >= 1) {
      payload.max_posts = v.max_posts;
    }
    const path = v.storage_state_path?.trim();
    if (path) payload.storage_state_path = path;
    const email = v.medium_email?.trim();
    if (email) payload.medium_email = email;
    const pw = v.medium_password;
    if (pw) payload.medium_password = pw;
    this.submitRequest.emit(payload);
    this.form.patchValue({ medium_password: '' });
  }
}
