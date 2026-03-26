import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { provideHttpClient } from '@angular/common/http';
import { Soc2ComplianceApiService } from '../../services/soc2-compliance-api.service';
import { Soc2ComplianceDashboardComponent } from './soc2-compliance-dashboard.component';

describe('Soc2ComplianceDashboardComponent', () => {
  let component: Soc2ComplianceDashboardComponent;
  let fixture: ComponentFixture<Soc2ComplianceDashboardComponent>;
  let apiSpy: { health: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    apiSpy = {
      health: vi.fn().mockReturnValue(of({ status: 'ok' })),
    };
    await TestBed.configureTestingModule({
      imports: [Soc2ComplianceDashboardComponent],
      providers: [provideHttpClient(), { provide: Soc2ComplianceApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(Soc2ComplianceDashboardComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('healthCheck should call api.health', () => {
    component.healthCheck().subscribe((r) => expect(r).toEqual({ status: 'ok' }));
    expect(apiSpy.health).toHaveBeenCalled();
  });
});
