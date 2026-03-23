import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import { PlanningV2PageComponent } from './planning-v2-page.component';

describe('PlanningV2PageComponent', () => {
  let component: PlanningV2PageComponent;
  let fixture: ComponentFixture<PlanningV2PageComponent>;

  beforeEach(async () => {
    const apiSpy = {
      health: vi.fn().mockReturnValue(of({ status: 'ok' })),
      getPlanningV2Jobs: vi.fn().mockReturnValue(of({ jobs: [] })),
      runPlanningV2: vi.fn(),
    };
    await TestBed.configureTestingModule({
      imports: [PlanningV2PageComponent, NoopAnimationsModule],
      providers: [
        { provide: SoftwareEngineeringApiService, useValue: apiSpy },
        { provide: ActivatedRoute, useValue: { queryParams: of({}) } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PlanningV2PageComponent);
    component = fixture.componentInstance;

    vi.useFakeTimers();
    fixture.detectChanges();
    vi.advanceTimersByTime(0);
  });

  afterEach(() => vi.useRealTimers());

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
