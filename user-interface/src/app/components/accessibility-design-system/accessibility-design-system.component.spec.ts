import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { AccessibilityDesignSystemComponent } from './accessibility-design-system.component';

describe('AccessibilityDesignSystemComponent', () => {
  let component: AccessibilityDesignSystemComponent;
  let fixture: ComponentFixture<AccessibilityDesignSystemComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AccessibilityDesignSystemComponent, NoopAnimationsModule],
      providers: [provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(AccessibilityDesignSystemComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
