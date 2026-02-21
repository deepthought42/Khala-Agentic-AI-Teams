import { Component, output } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCardModule } from '@angular/material/card';
import type { ResearchAndReviewRequest } from '../../models';

/**
 * Form for POST /research-and-review.
 * Emits the request payload on submit.
 */
@Component({
  selector: 'app-research-review-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
  ],
  templateUrl: './research-review-form.component.html',
  styleUrl: './research-review-form.component.scss',
})
export class ResearchReviewFormComponent {
  /** Emits when form is submitted with valid data. */
  readonly submitRequest = output<ResearchAndReviewRequest>();

  form: FormGroup;

  constructor(private readonly fb: FormBuilder) {
    this.form = this.fb.nonNullable.group({
      brief: ['', [Validators.required, Validators.minLength(3)]],
      title_concept: [''],
      audience: [''],
      tone_or_purpose: [''],
      max_results: [20, [Validators.required, Validators.min(1), Validators.max(50)]],
    });
  }

  onSubmit(): void {
    if (this.form.valid) {
      const v = this.form.getRawValue();
      this.submitRequest.emit({
        brief: v.brief,
        title_concept: v.title_concept || undefined,
        audience: v.audience || undefined,
        tone_or_purpose: v.tone_or_purpose || undefined,
        max_results: v.max_results,
      });
    }
  }
}
