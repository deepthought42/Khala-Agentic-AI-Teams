import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormArray,
  FormBuilder,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatStepperModule } from '@angular/material/stepper';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NutritionApiService } from '../../services/nutrition-api.service';
import type { ClientProfile, MealRecommendation, NutritionHouseholdMember, NutritionPlanResponse } from '../../models';

const CLIENT_ID_STORAGE_KEY = 'nutritionClientId';

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
    MatStepperModule,
    MatSelectModule,
    MatTooltipModule,
  ],
  templateUrl: './nutrition-dashboard.component.html',
  styleUrl: './nutrition-dashboard.component.scss',
})
export class NutritionDashboardComponent implements OnInit {
  private readonly api = inject(NutritionApiService);
  private readonly fb = inject(FormBuilder);

  loading = false;
  error: string | null = null;
  success: string | null = null;
  healthStatus: 'checking' | 'healthy' | 'unhealthy' = 'checking';

  clientId = '';
  selectedStepIndex = 0;
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
    household_description: [''],
    ages_if_relevant_csv: [''],
    dietary_needs_csv: [''],
    allergies_csv: [''],
    max_cooking_time_minutes: [30 as number | null],
    lunch_context: ['remote'],
    equipment_constraints_csv: [''],
    cuisines_liked_csv: [''],
    cuisines_disliked_csv: [''],
    ingredients_disliked_csv: [''],
    preferences_free_text: [''],
    goal_type: ['maintain'],
    goal_notes: [''],
    members: this.fb.array<FormGroup>([this.createMemberGroup()]),
  });

  readonly mealPlanForm = this.fb.nonNullable.group({
    period_days: [7, [Validators.required, Validators.min(1), Validators.max(30)]],
    meal_types_csv: ['breakfast,lunch,dinner'],
  });

  readonly lunchOptions = [
    { value: 'remote', label: 'Mostly at home (can cook or reheat)' },
    { value: 'office', label: 'Often away / need portable lunches' },
  ];

  readonly goalOptions = [
    { value: 'maintain', label: 'Maintain weight & feel good' },
    { value: 'lose_weight', label: 'Lose weight' },
    { value: 'gain_weight', label: 'Gain weight' },
    { value: 'muscle', label: 'Build muscle' },
    { value: 'other', label: 'Something else (notes below)' },
  ];

  constructor() {
    this.checkHealth();
  }

  ngOnInit(): void {
    const saved = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
    if (saved?.trim()) {
      this.clientId = saved.trim();
    }
  }

  suggestClientId(): void {
    const id =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? `home-${crypto.randomUUID().slice(0, 8)}`
        : `home-${Math.random().toString(36).slice(2, 10)}`;
    this.clientId = id;
  }

  get members(): FormArray<FormGroup> {
    return this.profileForm.get('members') as FormArray<FormGroup>;
  }

  /** Saved profile on the server — unlocks planning steps. */
  get hasProfile(): boolean {
    return this.profile !== null;
  }

  /** Meal ideas: backend runs the nutritionist internally; only a stored profile is required. */
  get canGenerateMeals(): boolean {
    return this.hasProfile && !!this.clientId.trim();
  }

  get hasMealSuggestions(): boolean {
    return this.mealRecommendations.length > 0;
  }

  get mealsByDay(): { key: string; label: string; meals: MealRecommendation[] }[] {
    const map = new Map<string, MealRecommendation[]>();
    for (const m of this.mealRecommendations) {
      const raw = m.suggested_date?.trim();
      const key = raw && raw.length > 0 ? raw : '_unscheduled';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(m);
    }
    const keys = [...map.keys()].sort((a, b) => {
      if (a === '_unscheduled') return 1;
      if (b === '_unscheduled') return -1;
      return a.localeCompare(b);
    });
    return keys.map((key) => ({
      key,
      label: key === '_unscheduled' ? 'Flexible timing' : key,
      meals: map.get(key)!,
    }));
  }

  checkHealth(): void {
    this.healthStatus = 'checking';
    this.api.healthCheck().subscribe({
      next: () => (this.healthStatus = 'healthy'),
      error: () => (this.healthStatus = 'unhealthy'),
    });
  }

  createMemberGroup(data?: Partial<NutritionHouseholdMember>): FormGroup {
    return this.fb.nonNullable.group({
      name: [data?.name ?? ''],
      age_or_role: [data?.age_or_role ?? ''],
      dietary_needs_csv: [(data?.dietary_needs ?? []).join(', ')],
      allergies_csv: [(data?.allergies ?? []).join(', ')],
      notes: [data?.notes ?? ''],
    });
  }

  addMember(): void {
    this.members.push(this.createMemberGroup());
  }

  removeMember(index: number): void {
    if (this.members.length <= 1) return;
    this.members.removeAt(index);
  }

  private persistClientId(id: string): void {
    localStorage.setItem(CLIENT_ID_STORAGE_KEY, id.trim());
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
        this.persistClientId(id);
        this.patchFormFromProfile(res);
        this.loading = false;
        this.success = 'Welcome back — I’ve pulled up your household profile.';
        this.selectedStepIndex = 1;
        this.nutritionPlan = null;
        this.mealRecommendations = [];
      },
      error: (err) => {
        this.loading = false;
        this.error = this.formatApiError(err, 'No saved profile for that ID yet. Fill in your household below and tap “Save household”.');
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
    const membersPayload = this.buildMembersPayload(raw);
    const headcount =
      membersPayload.length > 0 ? membersPayload.length : Math.max(1, raw.number_of_people);
    let description = raw.household_description.trim();
    if (!description && membersPayload.some((m) => m.name)) {
      description = `Household: ${membersPayload.map((m) => m.name || m.age_or_role || 'member').join(', ')}`;
    }
    if (!description) {
      description = headcount === 1 ? 'solo' : `household of ${headcount}`;
    }

    const agesFromCsv = this.csv(raw.ages_if_relevant_csv);
    const agesFromMembers = membersPayload.map((m) => m.age_or_role).filter(Boolean);
    const ages_if_relevant = agesFromCsv.length > 0 ? agesFromCsv : agesFromMembers;

    const householdAllergies = this.csv(raw.allergies_csv);
    const mergedAllergies = new Set<string>(householdAllergies);
    for (const m of membersPayload) {
      for (const a of m.allergies) mergedAllergies.add(a);
    }

    this.api
      .upsertProfile(id, {
        household: {
          number_of_people: headcount,
          description,
          ages_if_relevant,
          members: membersPayload,
        },
        dietary_needs: this.csv(raw.dietary_needs_csv),
        allergies_and_intolerances: [...mergedAllergies],
        lifestyle: {
          max_cooking_time_minutes: raw.max_cooking_time_minutes ?? null,
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
          this.persistClientId(id);
          this.loading = false;
          this.success =
            'Lovely — your household is on file. Next, peek at nutrition targets (optional) or jump straight to your week of meals.';
          this.selectedStepIndex = 1;
        },
        error: (err) => {
          this.loading = false;
          this.error = this.formatApiError(err, 'Could not save your profile. Check the API connection and try again.');
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
        this.success = 'Here’s how I’d aim your day nutritionally — you can still adjust meals in the next step.';
      },
      error: (err) => {
        this.loading = false;
        this.error = this.formatApiError(err, 'Nutrition plan could not be generated right now.');
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
        this.success =
          this.mealRecommendations.length > 0
            ? 'Your week is sketched out — tweak with feedback anytime.'
            : 'The planner responded but returned no meals. Try again or shorten the period.';
        if (this.mealRecommendations.length > 0) {
          this.selectedStepIndex = 3;
        }
      },
      error: (err) => {
        this.loading = false;
        this.error = this.formatApiError(err, 'Meal plan could not be generated.');
      },
    });
  }

  selectMealForFeedback(meal: MealRecommendation): void {
    this.feedbackRecommendationId = meal.recommendation_id;
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
          this.success = 'Thanks — that helps me tune your next plans.';
          this.feedbackNotes = '';
          this.loadHistory();
        },
        error: (err) => {
          this.loading = false;
          this.error = this.formatApiError(err, 'Feedback was not recorded.');
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
    const members = profile.household.members ?? [];
    this.members.clear();
    if (members.length === 0) {
      this.members.push(this.createMemberGroup());
    } else {
      for (const m of members) {
        this.members.push(this.createMemberGroup(m));
      }
    }

    this.profileForm.patchValue({
      number_of_people: profile.household.number_of_people || 1,
      household_description: profile.household.description || '',
      ages_if_relevant_csv: (profile.household.ages_if_relevant || []).join(', '),
      dietary_needs_csv: (profile.dietary_needs || []).join(', '),
      allergies_csv: (profile.allergies_and_intolerances || []).join(', '),
      max_cooking_time_minutes: profile.lifestyle.max_cooking_time_minutes ?? 30,
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

  private buildMembersPayload(raw: Record<string, unknown>): NutritionHouseholdMember[] {
    const arr = this.members.controls.map((ctrl) => {
      const g = ctrl.getRawValue() as {
        name: string;
        age_or_role: string;
        dietary_needs_csv: string;
        allergies_csv: string;
        notes: string;
      };
      return {
        name: g.name.trim(),
        age_or_role: g.age_or_role.trim(),
        dietary_needs: this.csv(g.dietary_needs_csv),
        allergies: this.csv(g.allergies_csv),
        notes: g.notes.trim(),
      };
    });
    return arr.filter(
      (m) =>
        m.name ||
        m.age_or_role ||
        m.dietary_needs.length > 0 ||
        m.allergies.length > 0 ||
        m.notes.length > 0,
    );
  }

  private csv(value: string): string[] {
    return value
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean);
  }

  private formatApiError(err: unknown, fallback: string): string {
    if (err && typeof err === 'object' && 'error' in err) {
      const e = err as { error?: { detail?: unknown; message?: string } };
      const d = e.error?.detail;
      if (typeof d === 'string' && d.trim()) return d;
      if (Array.isArray(d)) {
        const msgs = d.map((x: { msg?: string }) => x.msg).filter(Boolean);
        if (msgs.length) return msgs.join('; ');
      }
      if (typeof e.error?.message === 'string' && e.error.message) return e.error.message;
    }
    if (err && typeof err === 'object' && 'message' in err) {
      const m = (err as { message?: string }).message;
      if (typeof m === 'string' && m) return m;
    }
    return fallback;
  }
}
