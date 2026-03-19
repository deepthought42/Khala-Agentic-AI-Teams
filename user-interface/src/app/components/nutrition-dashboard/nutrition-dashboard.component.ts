import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { NutritionApiService } from '../../services/nutrition-api.service';
import type { ClientProfile, MealRecommendation, NutritionPlanResponse } from '../../models';

@Component({
  selector: 'app-nutrition-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule,
    MatChipsModule,
    MatDividerModule,
  ],
  templateUrl: './nutrition-dashboard.component.html',
  styleUrl: './nutrition-dashboard.component.scss',
})
export class NutritionDashboardComponent {
  private readonly api = inject(NutritionApiService);
  private readonly fb = inject(FormBuilder);

  loading = false;
  error: string | null = null;
  success: string | null = null;
  healthStatus: 'checking' | 'healthy' | 'unhealthy' = 'checking';

  clientId = '';
  profile: ClientProfile | null = null;
  nutritionPlan: NutritionPlanResponse | null = null;
  mealRecommendations: MealRecommendation[] = [];

  feedbackRecommendationId = '';
  feedbackRating: number | undefined;
  feedbackWouldMakeAgain: boolean | undefined;
  feedbackNotes = '';

  historyCount = 0;

  readonly profileForm = this.fb.nonNullable.group({
    number_of_people: [1, [Validators.required, Validators.min(1)]],
    household_description: ['solo'],
    ages_if_relevant_csv: [''],
    dietary_needs_csv: [''],
    allergies_csv: [''],
    max_cooking_time_minutes: [30],
    lunch_context: ['remote'],
    equipment_constraints_csv: [''],
    cuisines_liked_csv: [''],
    cuisines_disliked_csv: [''],
    ingredients_disliked_csv: [''],
    preferences_free_text: [''],
    goal_type: ['maintain'],
    goal_notes: [''],
  });

  readonly mealPlanForm = this.fb.nonNullable.group({
    period_days: [7, [Validators.required, Validators.min(1), Validators.max(30)]],
    meal_types_csv: ['lunch,dinner'],
  });

  constructor() {
    this.checkHealth();
  }

  get profileUnlocked(): boolean {
    return !!this.clientId.trim();
  }

  get nutritionUnlocked(): boolean {
    return !!this.profile;
  }

  get mealsUnlocked(): boolean {
    return !!this.nutritionPlan;
  }

  get feedbackUnlocked(): boolean {
    return this.mealRecommendations.length > 0;
  }

  checkHealth(): void {
    this.healthStatus = 'checking';
    this.api.healthCheck().subscribe({
      next: () => (this.healthStatus = 'healthy'),
      error: () => (this.healthStatus = 'unhealthy'),
    });
  }

  loadProfile(): void {
    const id = this.clientId.trim();
    if (!id) return;
    this.loading = true;
    this.error = null;
    this.success = null;
    this.api.getProfile(id).subscribe({
      next: (res) => {
        this.profile = res;
        this.patchFormFromProfile(res);
        this.loading = false;
        this.success = 'Loaded existing profile.';
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to load profile';
      },
    });
  }

  saveProfile(): void {
    const id = this.clientId.trim();
    if (!id || this.profileForm.invalid) return;
    this.loading = true;
    this.error = null;
    this.success = null;

    const raw = this.profileForm.getRawValue();
    this.api
      .upsertProfile(id, {
        household: {
          number_of_people: raw.number_of_people,
          description: raw.household_description.trim(),
          ages_if_relevant: this.csv(raw.ages_if_relevant_csv),
        },
        dietary_needs: this.csv(raw.dietary_needs_csv),
        allergies_and_intolerances: this.csv(raw.allergies_csv),
        lifestyle: {
          max_cooking_time_minutes: raw.max_cooking_time_minutes || null,
          lunch_context: raw.lunch_context.trim() || 'remote',
          equipment_constraints: this.csv(raw.equipment_constraints_csv),
          other_constraints: '',
        },
        preferences: {
          cuisines_liked: this.csv(raw.cuisines_liked_csv),
          cuisines_disliked: this.csv(raw.cuisines_disliked_csv),
          ingredients_disliked: this.csv(raw.ingredients_disliked_csv),
          preferences_free_text: raw.preferences_free_text.trim(),
        },
        goals: {
          goal_type: raw.goal_type.trim() || 'maintain',
          notes: raw.goal_notes.trim(),
        },
      })
      .subscribe({
        next: (res) => {
          this.profile = res;
          this.loading = false;
          this.success = 'Profile saved. Nutrition planning unlocked.';
        },
        error: (err) => {
          this.loading = false;
          this.error = err?.error?.detail ?? err?.message ?? 'Failed to save profile';
        },
      });
  }

  generateNutritionPlan(): void {
    const id = this.clientId.trim();
    if (!id) return;
    this.loading = true;
    this.error = null;
    this.success = null;
    this.api.generateNutritionPlan(id).subscribe({
      next: (res) => {
        this.nutritionPlan = res;
        this.loading = false;
        this.success = 'Nutrition plan generated. Meal planning unlocked.';
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to generate nutrition plan';
      },
    });
  }

  generateMealPlan(): void {
    const id = this.clientId.trim();
    if (!id || this.mealPlanForm.invalid) return;
    const raw = this.mealPlanForm.getRawValue();
    this.loading = true;
    this.error = null;
    this.success = null;
    this.api.generateMealPlan(id, raw.period_days, this.csv(raw.meal_types_csv)).subscribe({
      next: (res) => {
        this.mealRecommendations = res.suggestions ?? [];
        this.loading = false;
        this.success = 'Meal recommendations generated. Feedback and history unlocked.';
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to generate meal recommendations';
      },
    });
  }

  submitFeedback(): void {
    const id = this.clientId.trim();
    const recommendationId = this.feedbackRecommendationId.trim();
    if (!id || !recommendationId) return;
    this.loading = true;
    this.error = null;
    this.success = null;
    this.api
      .submitFeedback(id, recommendationId, this.feedbackRating, this.feedbackWouldMakeAgain, this.feedbackNotes)
      .subscribe({
        next: () => {
          this.loading = false;
          this.success = 'Feedback submitted.';
          this.feedbackNotes = '';
          this.loadHistory();
        },
        error: (err) => {
          this.loading = false;
          this.error = err?.error?.detail ?? err?.message ?? 'Failed to submit feedback';
        },
      });
  }

  loadHistory(): void {
    const id = this.clientId.trim();
    if (!id) return;
    this.api.getMealHistory(id).subscribe({
      next: (res) => {
        this.historyCount = res.entries.length;
      },
      error: () => {
        this.historyCount = 0;
      },
    });
  }

  private patchFormFromProfile(profile: ClientProfile): void {
    this.profileForm.patchValue({
      number_of_people: profile.household.number_of_people || 1,
      household_description: profile.household.description || '',
      ages_if_relevant_csv: (profile.household.ages_if_relevant || []).join(', '),
      dietary_needs_csv: (profile.dietary_needs || []).join(', '),
      allergies_csv: (profile.allergies_and_intolerances || []).join(', '),
      max_cooking_time_minutes: profile.lifestyle.max_cooking_time_minutes || 30,
      lunch_context: profile.lifestyle.lunch_context || 'remote',
      equipment_constraints_csv: (profile.lifestyle.equipment_constraints || []).join(', '),
      cuisines_liked_csv: (profile.preferences.cuisines_liked || []).join(', '),
      cuisines_disliked_csv: (profile.preferences.cuisines_disliked || []).join(', '),
      ingredients_disliked_csv: (profile.preferences.ingredients_disliked || []).join(', '),
      preferences_free_text: profile.preferences.preferences_free_text || '',
      goal_type: profile.goals.goal_type || 'maintain',
      goal_notes: profile.goals.notes || '',
    });
  }

  private csv(value: string): string[] {
    return value
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean);
  }
}
