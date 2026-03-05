import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { BloggingApiService } from '../../services/blogging-api.service';
import { BloggingDashboardComponent } from './blogging-dashboard.component';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

describe('BloggingDashboardComponent', () => {
  let component: BloggingDashboardComponent;
  let fixture: ComponentFixture<BloggingDashboardComponent>;
  let apiSpy: jasmine.SpyObj<BloggingApiService>;

  beforeEach(async () => {
    apiSpy = jasmine.createSpyObj('BloggingApiService', [
      'startResearchReviewAsync',
      'startFullPipelineAsync',
      'getJobs',
      'getJobStatus',
      'getJobArtifacts',
      'getJobArtifactContent',
    ]);
    apiSpy.getJobs.and.returnValue(of([]));

    await TestBed.configureTestingModule({
      imports: [BloggingDashboardComponent, NoopAnimationsModule],
      providers: [{ provide: BloggingApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(BloggingDashboardComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should fetch all jobs via getJobs(false) on init', () => {
    expect(apiSpy.getJobs).toHaveBeenCalledWith(false);
  });

  it('should call startResearchReviewAsync and refetch jobs on success', () => {
    apiSpy.startResearchReviewAsync.and.returnValue(of({ job_id: 'new-job-123' }));
    apiSpy.getJobs.and.returnValue(of([{ job_id: 'new-job-123', status: 'running', brief: 'Test', progress: 0 }]));

    component.onResearchReviewSubmit({ brief: 'Test', max_results: 20 });

    expect(apiSpy.startResearchReviewAsync).toHaveBeenCalledWith({
      brief: 'Test',
      max_results: 20,
    });
    expect(component.loading).toBeFalse();
  });

  it('should set error on startResearchReviewAsync failure', () => {
    apiSpy.startResearchReviewAsync.and.returnValue(
      throwError(() => ({ error: { detail: 'Server error' } }))
    );

    component.onResearchReviewSubmit({ brief: 'Test', max_results: 20 });

    expect(component.error).toBeTruthy();
    expect(component.loading).toBeFalse();
  });
});
