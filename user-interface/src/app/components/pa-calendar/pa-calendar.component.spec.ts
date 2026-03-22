import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { PaCalendarComponent } from './pa-calendar.component';

describe('PaCalendarComponent', () => {
  let component: PaCalendarComponent;
  let fixture: ComponentFixture<PaCalendarComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PaCalendarComponent, NoopAnimationsModule],
      providers: [provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(PaCalendarComponent);
    component = fixture.componentInstance;
    component.userId = 'u1';
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
