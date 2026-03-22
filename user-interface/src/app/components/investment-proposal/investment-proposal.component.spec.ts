import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { InvestmentProposalComponent } from './investment-proposal.component';

describe('InvestmentProposalComponent', () => {
  let component: InvestmentProposalComponent;
  let fixture: ComponentFixture<InvestmentProposalComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InvestmentProposalComponent, NoopAnimationsModule],
      providers: [provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(InvestmentProposalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
