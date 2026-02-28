import { Component, output } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCardModule } from '@angular/material/card';
import type { RunTeamRequest } from '../../models';

@Component({
  selector: 'app-run-team-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
  ],
  templateUrl: './run-team-form.component.html',
  styleUrl: './run-team-form.component.scss',
})
export class RunTeamFormComponent {
  readonly submitRequest = output<RunTeamRequest>();

  form: FormGroup;

  constructor(private readonly fb: FormBuilder) {
    this.form = this.fb.nonNullable.group({
      repo_path: ['', [Validators.required, Validators.minLength(1)]],
    });
  }

  onSubmit(): void {
    if (this.form.valid) {
      const v = this.form.getRawValue();
      this.submitRequest.emit({
        repo_path: v.repo_path,
      });
    }
  }
}
