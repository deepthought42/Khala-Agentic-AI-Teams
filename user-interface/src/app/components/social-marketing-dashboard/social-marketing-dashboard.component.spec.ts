import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { SocialMarketingDashboardComponent } from './social-marketing-dashboard.component';

describe('SocialMarketingDashboardComponent', () => {
  let component: SocialMarketingDashboardComponent;
  let fixture: ComponentFixture<SocialMarketingDashboardComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SocialMarketingDashboardComponent],
      providers: [provideHttpClient()],
    }).compileComponents();

    fixture = TestBed.createComponent(SocialMarketingDashboardComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
