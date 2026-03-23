import { Component, output, inject } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatCardModule } from '@angular/material/card';
import type { RunMarketResearchRequest, TeamTopology } from '../../models';

@Component({
  selector: 'app-market-research-form',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatButtonModule,
  ],
  templateUrl: './market-research-form.component.html',
  styleUrl: './market-research-form.component.scss',
})
export class MarketResearchFormComponent {
  private readonly fb = inject(FormBuilder);

  readonly submitRequest = output<RunMarketResearchRequest>();

  form: FormGroup;
  topologyOptions: { value: TeamTopology; label: string }[] = [
    { value: 'unified', label: 'Unified' },
    { value: 'split', label: 'Split' },
  ];

  constructor() {
    this.form = this.fb.nonNullable.group({
      product_concept: ['', [Validators.required, Validators.minLength(3)]],
      target_users: ['', [Validators.required, Validators.minLength(3)]],
      business_goal: ['', [Validators.required, Validators.minLength(3)]],
      topology: ['unified' as TeamTopology],
      transcript_folder_path: [''],
      transcripts: [''],
      human_approved: [false],
      human_feedback: [''],
    });
  }

  onSubmit(): void {
    if (this.form.valid) {
      const v = this.form.getRawValue();
      const transcripts = v.transcripts
        ? v.transcripts.split('\n').map((s: string) => s.trim()).filter(Boolean)
        : [];
      this.submitRequest.emit({
        product_concept: v.product_concept,
        target_users: v.target_users,
        business_goal: v.business_goal,
        topology: v.topology,
        transcript_folder_path: v.transcript_folder_path || undefined,
        transcripts,
        human_approved: v.human_approved,
        human_feedback: v.human_feedback || '',
      });
    }
  }
}
