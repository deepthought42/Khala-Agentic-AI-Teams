import { Component, Input, output } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatCardModule } from '@angular/material/card';
import type { ReviseMarketingTeamRequest } from '../../models';

@Component({
  selector: 'app-social-marketing-revise',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatCheckboxModule,
    MatButtonModule,
  ],
  templateUrl: './social-marketing-revise.component.html',
  styleUrl: './social-marketing-revise.component.scss',
})
export class SocialMarketingReviseComponent {
  @Input() jobId: string | null = null;

  readonly submitRequest = output<ReviseMarketingTeamRequest>();

  form: FormGroup;

  constructor(private readonly fb: FormBuilder) {
    this.form = this.fb.nonNullable.group({
      feedback: ['', [Validators.required, Validators.minLength(3)]],
      approved_for_testing: [false],
    });
  }

  onSubmit(): void {
    if (this.form.valid && this.jobId) {
      this.submitRequest.emit(this.form.getRawValue());
    }
  }
}
