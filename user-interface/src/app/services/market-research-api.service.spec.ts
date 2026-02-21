import { TestBed } from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import { MarketResearchApiService } from './market-research-api.service';
import { environment } from '../../environments/environment';

describe('MarketResearchApiService', () => {
  let service: MarketResearchApiService;
  let httpMock: HttpTestingController;
  const baseUrl = environment.marketResearchApiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [MarketResearchApiService],
    });
    service = TestBed.inject(MarketResearchApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should call POST /market-research/run', () => {
    const request = {
      product_concept: 'Concept',
      target_users: 'Users',
      business_goal: 'Goal',
    };
    const mockResponse = {
      status: 'draft',
      topology: 'unified',
      mission_summary: 'Summary',
      insights: [],
      market_signals: [],
      recommendation: { verdict: 'Go', confidence: 0.8 },
      proposed_research_scripts: [],
    };

    service.run(request).subscribe((res) => {
      expect(res.status).toBe('draft');
      expect(res.recommendation.verdict).toBe('Go');
    });

    const req = httpMock.expectOne(`${baseUrl}/market-research/run`);
    expect(req.request.method).toBe('POST');
    req.flush(mockResponse);
  });

  it('should call GET /health', () => {
    service.health().subscribe((res) => expect(res.status).toBe('ok'));
    const req = httpMock.expectOne(`${baseUrl}/health`);
    expect(req.request.method).toBe('GET');
    req.flush({ status: 'ok' });
  });
});
