import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { SoftwareEngineeringApiService } from '../../services/software-engineering-api.service';
import { RunTeamFormComponent } from './run-team-form.component';

describe('RunTeamFormComponent', () => {
  let component: RunTeamFormComponent;
  let fixture: ComponentFixture<RunTeamFormComponent>;
  let apiSpy: { runTeamFromUpload: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    apiSpy = { runTeamFromUpload: vi.fn().mockReturnValue(of({ job_id: 'j1', status: 'running', message: '' })) };
    await TestBed.configureTestingModule({
      imports: [RunTeamFormComponent, NoopAnimationsModule],
      providers: [{ provide: SoftwareEngineeringApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(RunTeamFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('form should be invalid when project_name is empty', () => {
    expect(component.form.valid).toBe(false);
    expect(component.form.get('project_name')?.errors?.['required']).toBeTruthy();
  });

  it('onSubmit should not emit when form is invalid', () => {
    let emitted = false;
    component.submitRequest.subscribe(() => (emitted = true));
    component.form.patchValue({ project_name: '' });
    component.onSubmit();
    expect(emitted).toBe(false);
  });

  it('onSubmit should call api.runTeamFromUpload when form valid and file selected', () => {
    component.form.patchValue({ project_name: 'my-project' });
    component.selectedFile = new File([''], 'spec.zip');
    component.onSubmit();
    expect(apiSpy.runTeamFromUpload).toHaveBeenCalledWith('my-project', expect.any(File));
  });
});
