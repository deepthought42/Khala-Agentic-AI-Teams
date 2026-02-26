import { Component, EventEmitter, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import type { ProductAnalysisRunRequest } from '../../models';

@Component({
  selector: 'app-product-analysis-run-form',
  standalone: true,
  imports: [
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
  ],
  templateUrl: './product-analysis-run-form.component.html',
  styleUrl: './product-analysis-run-form.component.scss',
})
export class ProductAnalysisRunFormComponent {
  @Output() submitRequest = new EventEmitter<ProductAnalysisRunRequest>();

  repoPath = '';
  specContent = '';

  submit(): void {
    if (!this.repoPath.trim()) return;

    const request: ProductAnalysisRunRequest = {
      repo_path: this.repoPath.trim(),
    };

    if (this.specContent.trim()) {
      request.spec_content = this.specContent.trim();
    }

    this.submitRequest.emit(request);
  }
}
