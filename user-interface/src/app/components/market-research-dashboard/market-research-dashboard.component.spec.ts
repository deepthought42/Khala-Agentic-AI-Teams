import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { provideHttpClient } from '@angular/common/http';
import { MarketResearchApiService } from '../../services/market-research-api.service';
import { MarketResearchDashboardComponent } from './market-research-dashboard.component';

describe('MarketResearchDashboardComponent', () => {
  let component: MarketResearchDashboardComponent;
  let fixture: ComponentFixture<MarketResearchDashboardComponent>;
  let apiSpy: { health: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    apiSpy = {
      health: vi.fn().mockReturnValue(of({ status: 'ok' })),
    };
    await TestBed.configureTestingModule({
      imports: [MarketResearchDashboardComponent],
      providers: [provideHttpClient(), { provide: MarketResearchApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(MarketResearchDashboardComponent);
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
