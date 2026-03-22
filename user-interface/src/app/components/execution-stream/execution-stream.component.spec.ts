import { ComponentFixture, TestBed } from '@angular/core/testing';
import { EMPTY } from 'rxjs';
import { vi } from 'vitest';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import { ExecutionStreamComponent } from './execution-stream.component';

describe('ExecutionStreamComponent', () => {
  let component: ExecutionStreamComponent;
  let fixture: ComponentFixture<ExecutionStreamComponent>;

  beforeEach(async () => {
    const apiSpy = { getExecutionStream: vi.fn().mockReturnValue(EMPTY) };
    await TestBed.configureTestingModule({
      imports: [ExecutionStreamComponent, NoopAnimationsModule],
      providers: [{ provide: SoftwareEngineeringApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(ExecutionStreamComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
