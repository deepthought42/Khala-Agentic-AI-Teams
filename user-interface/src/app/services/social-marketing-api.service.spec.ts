import { TestBed } from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import { SocialMarketingApiService } from './social-marketing-api.service';
import { environment } from '../../environments/environment';

describe('SocialMarketingApiService', () => {
  let service: SocialMarketingApiService;
  let httpMock: HttpTestingController;
  const baseUrl = environment.socialMarketingApiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [SocialMarketingApiService],
    });
    service = TestBed.inject(SocialMarketingApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should call POST /social-marketing/run', () => {
    const req = {
      brand_guidelines_path: '/a',
      brand_objectives_path: '/b',
      llm_model_name: 'model',
    };
    service.run(req).subscribe((res) => expect(res.job_id).toBeDefined());
    const httpReq = httpMock.expectOne(`${baseUrl}/social-marketing/run`);
    expect(httpReq.request.method).toBe('POST');
    httpReq.flush({ job_id: '1', status: 'running', message: 'OK' });
  });

  it('should call GET /social-marketing/status/{id}', () => {
    service.getStatus('1').subscribe((res) => expect(res.job_id).toBe('1'));
    const req = httpMock.expectOne(`${baseUrl}/social-marketing/status/1`);
    expect(req.request.method).toBe('GET');
    req.flush({
      job_id: '1',
      status: 'completed',
      current_stage: 'done',
      progress: 100,
      llm_model_name: 'm',
      brand_guidelines_path: '/a',
      brand_objectives_path: '/b',
      last_updated_at: new Date().toISOString(),
    });
  });
});
