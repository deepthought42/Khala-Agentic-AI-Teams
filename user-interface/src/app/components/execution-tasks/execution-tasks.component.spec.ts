import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import { ExecutionTasksComponent } from './execution-tasks.component';

describe('ExecutionTasksComponent', () => {
  let component: ExecutionTasksComponent;
  let fixture: ComponentFixture<ExecutionTasksComponent>;

  beforeEach(async () => {
    const apiSpy = { getExecutionTasks: vi.fn().mockReturnValue(of({})) };
    await TestBed.configureTestingModule({
      imports: [ExecutionTasksComponent, NoopAnimationsModule],
      providers: [{ provide: SoftwareEngineeringApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(ExecutionTasksComponent);
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
