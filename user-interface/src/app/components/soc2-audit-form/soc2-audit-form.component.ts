import { Component, output, inject } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCardModule } from '@angular/material/card';
import type { RunAuditRequest } from '../../models';

@Component({
  selector: 'app-soc2-audit-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
  ],
  templateUrl: './soc2-audit-form.component.html',
  styleUrl: './soc2-audit-form.component.scss',
})
export class Soc2AuditFormComponent {
  private readonly fb = inject(FormBuilder);

  readonly submitRequest = output<RunAuditRequest>();

  form: FormGroup;

  constructor() {
    this.form = this.fb.nonNullable.group({
      repo_path: ['', [Validators.required, Validators.minLength(1)]],
    });
  }

  onSubmit(): void {
    if (this.form.valid) {
      this.submitRequest.emit({
        repo_path: this.form.getRawValue().repo_path,
      });
    }
  }
}
