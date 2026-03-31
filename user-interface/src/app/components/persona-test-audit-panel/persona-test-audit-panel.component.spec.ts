import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { PersonaTestAuditPanelComponent } from './persona-test-audit-panel.component';

describe('PersonaTestAuditPanelComponent', () => {
  let component: PersonaTestAuditPanelComponent;
  let fixture: ComponentFixture<PersonaTestAuditPanelComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PersonaTestAuditPanelComponent],
      providers: [provideHttpClient(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(PersonaTestAuditPanelComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
