import { TestBed } from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import { SoftwareEngineeringApiService } from './software-engineering-api.service';
import { environment } from '../../environments/environment';

describe('SoftwareEngineeringApiService', () => {
  let service: SoftwareEngineeringApiService;
  let httpMock: HttpTestingController;
  const baseUrl = environment.softwareEngineeringApiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [SoftwareEngineeringApiService],
    });
    service = TestBed.inject(SoftwareEngineeringApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should call POST /run-team', () => {
    service.runTeam({ repo_path: '/tmp' }).subscribe((res) => {
      expect(res.job_id).toBeDefined();
    });
    const req = httpMock.expectOne(`${baseUrl}/run-team`);
    expect(req.request.method).toBe('POST');
    req.flush({ job_id: '1', status: 'running', message: 'OK' });
  });

  it('should call GET /run-team/{id}', () => {
    service.getJobStatus('1').subscribe((res) => expect(res.job_id).toBe('1'));
    const req = httpMock.expectOne(`${baseUrl}/run-team/1`);
    expect(req.request.method).toBe('GET');
    req.flush({ job_id: '1', status: 'running', task_results: [], task_ids: [], failed_tasks: [] });
  });

});
