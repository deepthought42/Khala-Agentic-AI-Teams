import { Component, output, inject } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import type { MediumStatsRequest } from '../../models';

/**
 * Form for POST /medium-stats-async. Medium sign-in is configured under Integrations (stored session).
 */
@Component({
  selector: 'app-medium-stats-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    RouterLink,
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
  private readonly fb = inject(FormBuilder);

  readonly submitRequest = output<MediumStatsRequest>();

  readonly form: FormGroup;

  constructor() {
    this.form = this.fb.nonNullable.group({
      headless: [true],
      timeout_ms: [90_000, [Validators.required, Validators.min(5000), Validators.max(600_000)]],
      max_posts: [null as number | null],
    });
  }

  onSubmit(): void {
    if (this.form.invalid) return;
    const v = this.form.getRawValue() as {
      headless: boolean;
      timeout_ms: number;
      max_posts: number | null;
    };
    const payload: MediumStatsRequest = {
      headless: v.headless,
      timeout_ms: v.timeout_ms,
    };
    if (v.max_posts != null && v.max_posts >= 1) {
      payload.max_posts = v.max_posts;
    }
    this.submitRequest.emit(payload);
  }
}
