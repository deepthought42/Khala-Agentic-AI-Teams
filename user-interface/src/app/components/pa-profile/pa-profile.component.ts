import { Component, Input, Output, EventEmitter, inject, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { FormBuilder, FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDividerModule } from '@angular/material/divider';
import { PersonalAssistantApiService } from '../../services/personal-assistant-api.service';
import type { UserProfile } from '../../models';

interface ProfileForm {
  userId: FormControl<string>;
  fullName: FormControl<string>;
  preferredName: FormControl<string>;
  email: FormControl<string>;
  timezone: FormControl<string>;
  foodLikes: FormControl<string>;
  foodDislikes: FormControl<string>;
  cuisines: FormControl<string>;
  dietaryRestrictions: FormControl<string>;
  shortTermGoals: FormControl<string>;
  longTermGoals: FormControl<string>;
  dreams: FormControl<string>;
  jobTitle: FormControl<string>;
  company: FormControl<string>;
  industry: FormControl<string>;
  workSchedule: FormControl<string>;
}

/**
 * Profile management component for editing user preferences.
 */
@Component({
  selector: 'app-pa-profile',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatDividerModule,
  ],
  templateUrl: './pa-profile.component.html',
  styleUrl: './pa-profile.component.scss',
})
export class PaProfileComponent implements OnInit, OnChanges {
  @Input() userId = 'default';
  @Output() userIdChange = new EventEmitter<string>();

  private readonly api = inject(PersonalAssistantApiService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  loading = false;
  form: FormGroup<ProfileForm>;

  timezones = [
    { value: 'UTC', label: 'UTC' },
    { value: 'America/New_York', label: 'Eastern Time' },
    { value: 'America/Chicago', label: 'Central Time' },
    { value: 'America/Denver', label: 'Mountain Time' },
    { value: 'America/Los_Angeles', label: 'Pacific Time' },
    { value: 'Europe/London', label: 'London' },
    { value: 'Europe/Paris', label: 'Paris' },
    { value: 'Asia/Tokyo', label: 'Tokyo' },
  ];

  constructor() {
    this.form = this.fb.nonNullable.group({
      userId: 'default',
      fullName: '',
      preferredName: '',
      email: '',
      timezone: 'UTC',
      foodLikes: '',
      foodDislikes: '',
      cuisines: '',
      dietaryRestrictions: '',
      shortTermGoals: '',
      longTermGoals: '',
      dreams: '',
      jobTitle: '',
      company: '',
      industry: '',
      workSchedule: '',
    });
  }

  ngOnInit(): void {
    this.form.patchValue({ userId: this.userId });
    this.loadProfile();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['userId'] && !changes['userId'].firstChange) {
      this.form.patchValue({ userId: this.userId });
      this.loadProfile();
    }
  }

  private loadProfile(): void {
    this.loading = true;
    this.api.getProfile(this.userId).subscribe({
      next: (profile) => {
        this.populateForm(profile);
        this.loading = false;
      },
      error: () => {
        this.loading = false;
      },
    });
  }

  private populateForm(profile: UserProfile): void {
    this.form.patchValue({
      fullName: profile.identity?.full_name || '',
      preferredName: profile.identity?.preferred_name || '',
      email: profile.identity?.email || '',
      timezone: profile.identity?.timezone || 'UTC',
      foodLikes: (profile.preferences?.food_likes || []).join(', '),
      foodDislikes: (profile.preferences?.food_dislikes || []).join(', '),
      cuisines: (profile.preferences?.cuisines_ranked || []).join(', '),
      dietaryRestrictions: (profile.preferences?.dietary_restrictions || []).join(', '),
      shortTermGoals: (profile.goals?.short_term_goals || []).join('\n'),
      longTermGoals: (profile.goals?.long_term_goals || []).join('\n'),
      dreams: (profile.goals?.dreams || []).join('\n'),
      jobTitle: profile.professional?.job_title || '',
      company: profile.professional?.company || '',
      industry: profile.professional?.industry || '',
      workSchedule: profile.professional?.work_schedule || '',
    });
  }

  onUserIdBlur(): void {
    const newUserId = this.form.get('userId')?.value?.trim();
    if (newUserId && newUserId !== this.userId) {
      this.userId = newUserId;
      this.userIdChange.emit(newUserId);
      this.loadProfile();
    }
  }

  private parseList(value: string, separator = ','): string[] {
    return value
      .split(separator)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }

  onSave(): void {
    this.loading = true;
    const formValue = this.form.getRawValue();

    const updates = [
      {
        category: 'identity',
        data: {
          full_name: formValue.fullName,
          preferred_name: formValue.preferredName,
          email: formValue.email,
          timezone: formValue.timezone,
        },
      },
      {
        category: 'preferences',
        data: {
          food_likes: this.parseList(formValue.foodLikes),
          food_dislikes: this.parseList(formValue.foodDislikes),
          cuisines_ranked: this.parseList(formValue.cuisines),
          dietary_restrictions: this.parseList(formValue.dietaryRestrictions),
        },
      },
      {
        category: 'goals',
        data: {
          short_term_goals: this.parseList(formValue.shortTermGoals, '\n'),
          long_term_goals: this.parseList(formValue.longTermGoals, '\n'),
          dreams: this.parseList(formValue.dreams, '\n'),
        },
      },
      {
        category: 'professional',
        data: {
          job_title: formValue.jobTitle,
          company: formValue.company,
          industry: formValue.industry,
          work_schedule: formValue.workSchedule,
        },
      },
    ];

    let completed = 0;
    for (const update of updates) {
      this.api.updateProfile(this.userId, { ...update, merge: true }).subscribe({
        next: () => {
          completed++;
          if (completed === updates.length) {
            this.loading = false;
            this.snackBar.open('Profile saved successfully!', 'Close', { duration: 3000 });
          }
        },
        error: () => {
          completed++;
          if (completed === updates.length) {
            this.loading = false;
            this.snackBar.open('Failed to save some profile sections', 'Close', { duration: 3000 });
          }
        },
      });
    }
  }
}
