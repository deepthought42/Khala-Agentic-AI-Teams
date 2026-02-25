import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatRadioModule } from '@angular/material/radio';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import type { PendingQuestion, AnswerSubmission, JobStatusResponse, PlanningV2StatusResponse } from '../../models';

/** Endpoint type determines which API to call for submitting answers. */
export type SubmitEndpointType = 'run-team' | 'planning-v2';

interface QuestionAnswer {
  questionId: string;
  selectedOptionId: string | null;
  otherText: string;
}

@Component({
  selector: 'app-pending-questions',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatRadioModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './pending-questions.component.html',
  styleUrl: './pending-questions.component.scss',
})
export class PendingQuestionsComponent implements OnChanges {
  private readonly api = inject(SoftwareEngineeringApiService);

  @Input() jobId: string | null = null;
  @Input() questions: PendingQuestion[] = [];
  /** Which endpoint to call: 'run-team' (default) or 'planning-v2'. */
  @Input() submitEndpoint: SubmitEndpointType = 'run-team';
  @Output() answersSubmitted = new EventEmitter<JobStatusResponse | PlanningV2StatusResponse>();

  answers: Map<string, QuestionAnswer> = new Map();
  submitting = false;
  error: string | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['questions']) {
      this.initializeAnswers();
    }
  }

  private initializeAnswers(): void {
    this.answers.clear();
    for (const q of this.questions) {
      this.answers.set(q.id, {
        questionId: q.id,
        selectedOptionId: null,
        otherText: '',
      });
    }
  }

  getAnswer(questionId: string): QuestionAnswer | undefined {
    return this.answers.get(questionId);
  }

  onOptionChange(questionId: string, optionId: string): void {
    const answer = this.answers.get(questionId);
    if (answer) {
      answer.selectedOptionId = optionId;
      if (optionId !== 'other') {
        answer.otherText = '';
      }
    }
  }

  onOtherTextChange(questionId: string, text: string): void {
    const answer = this.answers.get(questionId);
    if (answer) {
      answer.otherText = text;
    }
  }

  isOtherSelected(questionId: string): boolean {
    const answer = this.answers.get(questionId);
    return answer?.selectedOptionId === 'other';
  }

  isQuestionAnswered(question: PendingQuestion): boolean {
    const answer = this.answers.get(question.id);
    if (!answer) return false;
    if (!answer.selectedOptionId) return false;
    if (answer.selectedOptionId === 'other' && !answer.otherText.trim()) {
      return false;
    }
    return true;
  }

  get allRequiredAnswered(): boolean {
    return this.questions
      .filter((q) => q.required)
      .every((q) => this.isQuestionAnswered(q));
  }

  get answeredCount(): number {
    return this.questions.filter((q) => this.isQuestionAnswered(q)).length;
  }

  submitAnswers(): void {
    if (!this.jobId || !this.allRequiredAnswered) return;

    const submissions: AnswerSubmission[] = [];
    for (const q of this.questions) {
      const answer = this.answers.get(q.id);
      if (answer && answer.selectedOptionId) {
        submissions.push({
          question_id: q.id,
          selected_option_id: answer.selectedOptionId,
          other_text: answer.selectedOptionId === 'other' ? answer.otherText : null,
        });
      }
    }

    this.submitting = true;
    this.error = null;

    const request = { answers: submissions };

    const handleSuccess = (response: JobStatusResponse | PlanningV2StatusResponse): void => {
      this.submitting = false;
      this.answersSubmitted.emit(response);
    };

    const handleError = (err: { error?: { detail?: string }; message?: string }): void => {
      this.submitting = false;
      this.error = err?.error?.detail ?? err?.message ?? 'Failed to submit answers';
    };

    if (this.submitEndpoint === 'planning-v2') {
      this.api.submitPlanningV2Answers(this.jobId, request).subscribe({
        next: handleSuccess,
        error: handleError,
      });
    } else {
      this.api.submitAnswers(this.jobId, request).subscribe({
        next: handleSuccess,
        error: handleError,
      });
    }
  }
}
