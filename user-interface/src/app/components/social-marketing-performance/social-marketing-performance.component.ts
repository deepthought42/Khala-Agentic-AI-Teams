import { Component, Input, output, inject } from '@angular/core';

import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCardModule } from '@angular/material/card';
import type { PostPerformanceObservation } from '../../models';

@Component({
  selector: 'app-social-marketing-performance',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
  ],
  templateUrl: './social-marketing-performance.component.html',
  styleUrl: './social-marketing-performance.component.scss',
})
export class SocialMarketingPerformanceComponent {
  private readonly fb = inject(FormBuilder);

  @Input() jobId: string | null = null;

  readonly submitObservations = output<PostPerformanceObservation[]>();

  form: FormGroup;

  constructor() {
    this.form = this.fb.nonNullable.group({
      observationsJson: ['[]', Validators.required],
    });
  }

  onSubmit(): void {
    if (this.form.valid && this.jobId) {
      try {
        const obs = JSON.parse(
          this.form.getRawValue().observationsJson
        ) as PostPerformanceObservation[];
        this.submitObservations.emit(Array.isArray(obs) ? obs : []);
      } catch {
        // Invalid JSON - could show error
      }
    }
  }
}
