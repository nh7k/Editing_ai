import { api, ApiError, DEFAULT_TIMEOUT_MS, parseErrorBody, withApiKey } from '../src/api/client';
import { DEFAULT_BASE_URL, setApiKey } from '../src/store/settings';
import { project } from './fixtures';

type FetchMock = jest.Mock<Promise<Response>, [RequestInfo | URL, RequestInit | undefined]>;

function mockResponse(status: number, body: unknown): Response {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(text),
  } as unknown as Response;
}

describe('api client', () => {
  let fetchMock: FetchMock;
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    fetchMock = jest.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(async () => {
    globalThis.fetch = originalFetch;
    jest.useRealTimers();
    await setApiKey('');
  });

  const headersOf = (i = 0) => fetchMock.mock.calls[i][1]?.headers as Record<string, string>;

  it('GET /projects returns parsed JSON from the configured base URL', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, [project]));
    const result = await api.listProjects();
    expect(result).toEqual([project]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${DEFAULT_BASE_URL}/projects`);
    expect(init?.method).toBe('GET');
  });

  it('POST /projects/{id}/edit sends a JSON body', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(202, { job_id: 'j9', status: 'queued' }));
    const res = await api.startEdit('p1', { prompt: 'Trim to 15s', resolution: 720, aspect_ratio: '9:16' });
    expect(res).toEqual({ job_id: 'j9', status: 'queued' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${DEFAULT_BASE_URL}/projects/p1/edit`);
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ prompt: 'Trim to 15s', resolution: 720, aspect_ratio: '9:16' });
    expect((init?.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('parses the {"error":{code,message}} shape into an ApiError', async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(404, { error: { code: 'project_not_found', message: 'Project p404 does not exist' } }),
    );
    const err = await api.getProject('p404').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('project_not_found');
    expect((err as ApiError).message).toBe('Project p404 does not exist');
    expect((err as ApiError).status).toBe(404);
  });

  it('falls back to http_<status> for non-JSON error bodies', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(502, '<html>Bad gateway</html>'));
    const err = (await api.getScoreboard().catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('http_502');
    expect(err.status).toBe(502);
  });

  it('handles FastAPI {"detail": "..."} errors', () => {
    const err = parseErrorBody(422, JSON.stringify({ detail: 'prompt is required' }));
    expect(err.code).toBe('http_422');
    expect(err.message).toBe('prompt is required');
  });

  it('maps network failures to network_error', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'));
    const err = (await api.health().catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('network_error');
  });

  it('aborts and raises a timeout error when the backend does not answer in time', async () => {
    jest.useFakeTimers();
    fetchMock.mockImplementationOnce(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            const e = new Error('Aborted');
            e.name = 'AbortError';
            reject(e);
          });
        }),
    );
    const pending = api.listProjects().catch((e: unknown) => e);
    jest.advanceTimersByTime(DEFAULT_TIMEOUT_MS + 10);
    const err = (await pending) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('timeout');
    expect(init(fetchMock)?.signal?.aborted).toBe(true);
  });

  it('builds thumbnail and output URLs', () => {
    expect(api.thumbnailUrl('p1', 'c1')).toBe(`${DEFAULT_BASE_URL}/projects/p1/clips/c1/thumbnail`);
    expect(api.outputUrl('p1', 'j1')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?v=j1`);
    expect(api.outputUrl('p1')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output`);
  });

  it('does not send X-API-Key when no key is set', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, [project]));
    await api.listProjects();
    expect(headersOf()).not.toHaveProperty('X-API-Key');
    expect(headersOf().Accept).toBe('application/json');
  });

  it('sends X-API-Key on GET and POST requests when a key is set', async () => {
    await setApiKey('s3cret');
    fetchMock.mockResolvedValueOnce(mockResponse(200, [project]));
    fetchMock.mockResolvedValueOnce(mockResponse(202, { job_id: 'j9', status: 'queued' }));
    await api.listProjects();
    await api.startEdit('p1', { prompt: 'x' });
    expect(headersOf(0)['X-API-Key']).toBe('s3cret');
    expect(headersOf(1)['X-API-Key']).toBe('s3cret');
    expect(headersOf(1)['Content-Type']).toBe('application/json');
  });

  it('healthAt never sends the API key', async () => {
    await setApiKey('s3cret');
    fetchMock.mockResolvedValueOnce(mockResponse(200, { status: 'ok' }));
    await api.healthAt('http://10.0.2.2:8000');
    const [url, reqInit] = fetchMock.mock.calls[0];
    expect(url).toBe('http://10.0.2.2:8000/health');
    expect((reqInit?.headers as Record<string, string> | undefined)?.['X-API-Key']).toBeUndefined();
  });

  it('appends api_key to media URLs with the right separator', async () => {
    await setApiKey('a b&c');
    expect(api.thumbnailUrl('p1', 'c1')).toBe(`${DEFAULT_BASE_URL}/projects/p1/clips/c1/thumbnail?api_key=a%20b%26c`);
    expect(api.outputUrl('p1', 'j1')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?v=j1&api_key=a%20b%26c`);
    expect(api.outputUrl('p1')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?api_key=a%20b%26c`);
    expect(withApiKey('http://h/x', '')).toBe('http://h/x');
  });

  it('adds format to output URLs only when it is not mp4', async () => {
    expect(api.outputUrl('p1', 'j1', 'mp4')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?v=j1`);
    expect(api.outputUrl('p1', null, 'mp4')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output`);
    expect(api.outputUrl('p1', 'j1', 'gif')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?v=j1&format=gif`);
    expect(api.outputUrl('p1', undefined, 'mp3')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?format=mp3`);

    await setApiKey('k&1');
    expect(api.outputUrl('p1', 'j1', 'gif')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?v=j1&format=gif&api_key=k%261`);
    expect(api.outputUrl('p1', null, 'mp3')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?format=mp3&api_key=k%261`);
    expect(api.outputUrl('p1', 'j1', 'mp4')).toBe(`${DEFAULT_BASE_URL}/projects/p1/output?v=j1&api_key=k%261`);
  });

  it('maps 401 unauthorized to a clear error pointing at Settings', async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(401, { error: { code: 'unauthorized', message: 'Missing or wrong API key.' } }),
    );
    const err = (await api.listProjects().catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('unauthorized');
    expect(err.status).toBe(401);
    expect(err.message).toContain('Missing or wrong API key.');
    expect(err.message).toContain('API key in Settings');
  });
});

function init(mock: FetchMock): RequestInit | undefined {
  return mock.mock.calls[0]?.[1];
}
