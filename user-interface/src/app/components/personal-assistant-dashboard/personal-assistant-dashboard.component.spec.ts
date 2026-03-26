import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { PersonalAssistantApiService } from '../../services/personal-assistant-api.service';
import { PersonalAssistantDashboardComponent } from './personal-assistant-dashboard.component';

describe('PersonalAssistantDashboardComponent', () => {
  let component: PersonalAssistantDashboardComponent;
  let fixture: ComponentFixture<PersonalAssistantDashboardComponent>;

  beforeEach(async () => {
    const apiSpy = {
      health: vi.fn().mockReturnValue(of({ status: 'ok' })),
    };
    await TestBed.configureTestingModule({
      imports: [PersonalAssistantDashboardComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: PersonalAssistantApiService, useValue: apiSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PersonalAssistantDashboardComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('healthCheck calls api.health', () => {
    const api = TestBed.inject(PersonalAssistantApiService) as { health: ReturnType<typeof vi.fn> };
    component.healthCheck().subscribe((r) => expect(r).toEqual({ status: 'ok' }));
    expect(api.health).toHaveBeenCalled();
  });
});
