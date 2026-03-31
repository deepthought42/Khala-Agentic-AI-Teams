import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { PersonaTestingDashboardComponent } from './persona-testing-dashboard.component';

describe('PersonaTestingDashboardComponent', () => {
  let component: PersonaTestingDashboardComponent;
  let fixture: ComponentFixture<PersonaTestingDashboardComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PersonaTestingDashboardComponent],
      providers: [provideHttpClient(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(PersonaTestingDashboardComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
