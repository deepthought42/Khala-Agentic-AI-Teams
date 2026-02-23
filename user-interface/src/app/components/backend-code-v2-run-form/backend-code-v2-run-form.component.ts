import { Component, EventEmitter, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import type { BackendCodeV2RunRequest } from '../../models';

@Component({
  selector: 'app-backend-code-v2-run-form',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatChipsModule,
    MatIconModule,
  ],
  templateUrl: './backend-code-v2-run-form.component.html',
  styleUrl: './backend-code-v2-run-form.component.scss',
})
export class BackendCodeV2RunFormComponent {
  @Output() submitRequest = new EventEmitter<BackendCodeV2RunRequest>();

  title = '';
  description = '';
  requirements = '';
  repoPath = '';
  specContent = '';
  architecture = '';
  criterionInput = '';
  acceptanceCriteria: string[] = [];

  addCriterion(): void {
    const val = this.criterionInput.trim();
    if (val) {
      this.acceptanceCriteria.push(val);
      this.criterionInput = '';
    }
  }

  removeCriterion(index: number): void {
    this.acceptanceCriteria.splice(index, 1);
  }

  get canSubmit(): boolean {
    return !!(this.title.trim() && this.description.trim() && this.repoPath.trim());
  }

  onSubmit(): void {
    if (!this.canSubmit) return;
    const request: BackendCodeV2RunRequest = {
      task: {
        title: this.title.trim(),
        description: this.description.trim(),
        requirements: this.requirements.trim() || undefined,
        acceptance_criteria: this.acceptanceCriteria.length ? this.acceptanceCriteria : undefined,
      },
      repo_path: this.repoPath.trim(),
      spec_content: this.specContent.trim() || undefined,
      architecture: this.architecture.trim() || undefined,
    };
    this.submitRequest.emit(request);
  }
}
