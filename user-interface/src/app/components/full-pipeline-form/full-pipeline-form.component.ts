import { Component, output } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatCardModule } from '@angular/material/card';
import type { FullPipelineRequest } from '../../models';

/**
 * Form for POST /full-pipeline.
 * Emits the request payload on submit.
 */
@Component({
  selector: 'app-full-pipeline-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSlideToggleModule,
    MatButtonModule,
  ],
  templateUrl: './full-pipeline-form.component.html',
  styleUrl: './full-pipeline-form.component.scss',
})
export class FullPipelineFormComponent {
  readonly submitRequest = output<FullPipelineRequest>();

  form: FormGroup;

  constructor(private readonly fb: FormBuilder) {
    this.form = this.fb.nonNullable.group({
      brief: ['', [Validators.required, Validators.minLength(3)]],
      title_concept: [''],
      audience: [''],
      tone_or_purpose: [''],
      max_results: [20, [Validators.required, Validators.min(1), Validators.max(50)]],
      run_gates: [true],
      max_rewrite_iterations: [3, [Validators.required, Validators.min(1), Validators.max(10)]],
      target_word_count: [1000, [Validators.required, Validators.min(100), Validators.max(10000)]],
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
        run_gates: v.run_gates,
        max_rewrite_iterations: v.max_rewrite_iterations,
        target_word_count: v.target_word_count,
      });
    }
  }
}
