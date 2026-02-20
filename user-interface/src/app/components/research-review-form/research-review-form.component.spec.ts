import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ResearchReviewFormComponent } from './research-review-form.component';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';

describe('ResearchReviewFormComponent', () => {
  let component: ResearchReviewFormComponent;
  let fixture: ComponentFixture<ResearchReviewFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        ResearchReviewFormComponent,
        ReactiveFormsModule,
        MatFormFieldModule,
        MatInputModule,
        MatButtonModule,
        MatCardModule,
        NoopAnimationsModule,
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ResearchReviewFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should emit submitRequest when form is valid', () => {
    const emitSpy = jasmine.createSpy('submitRequest');
    component.submitRequest.subscribe(emitSpy);

    component.form.patchValue({
      brief: 'A valid brief for testing',
      max_results: 20,
    });
    component.onSubmit();

    expect(emitSpy).toHaveBeenCalledWith(
      jasmine.objectContaining({
        brief: 'A valid brief for testing',
        max_results: 20,
      })
    );
  });

  it('should not emit when brief is empty', () => {
    const emitSpy = jasmine.createSpy('submitRequest');
    component.submitRequest.subscribe(emitSpy);

    component.form.patchValue({ brief: '', max_results: 20 });
    component.onSubmit();

    expect(emitSpy).not.toHaveBeenCalled();
  });
});
