import { api } from '../src/api/client';
import { DEFAULT_BASE_URL, setApiKey } from '../src/store/settings';

type FetchMock = jest.Mock<Promise<Response>, [RequestInfo | URL, RequestInit | undefined]>;

function mockResponse(status: number, body: unknown): Response {
  const text = JSON.stringify(body);
  return { ok: status >= 200 && status < 300, status, text: () => Promise.resolve(text) } as unknown as Response;
}

describe('live / copy-edit / templates api', () => {
  let fetchMock: FetchMock;
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    fetchMock = jest.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });
  afterEach(async () => {
    globalThis.fetch = originalFetch;
    await setApiKey('');
  });

  it('mediaUrl prefixes server paths with the base URL and adds the api key', async () => {
    expect(api.mediaUrl('/projects/p1/clips/c1/frame?t=14.3')).toBe(`${DEFAULT_BASE_URL}/projects/p1/clips/c1/frame?t=14.3`);
    await setApiKey('k1');
    expect(api.mediaUrl('/templates/tpl_a/preview')).toBe(`${DEFAULT_BASE_URL}/templates/tpl_a/preview?api_key=k1`);
    expect(api.mediaUrl('https://cdn.example/x.jpg')).toBe('https://cdn.example/x.jpg?api_key=k1');
  });

  it('getCopyEdit returns null on 404 no_blueprint and the state otherwise', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(404, { error: { code: 'no_blueprint', message: 'none' } }));
    expect(await api.getCopyEdit('p1')).toBeNull();
    fetchMock.mockResolvedValueOnce(mockResponse(200, { status: 'analyzing', progress: 0.5, step: 'Reading on-screen text…' }));
    expect(await api.getCopyEdit('p1')).toEqual({ status: 'analyzing', progress: 0.5, step: 'Reading on-screen text…' });
    expect(fetchMock.mock.calls[1][0]).toBe(`${DEFAULT_BASE_URL}/projects/p1/copy-edit`);
  });

  it('runCopyEdit / saveCopyEditTemplate / applyTemplate / deleteTemplate send the contract bodies', async () => {
    fetchMock.mockResolvedValue(mockResponse(202, { job_id: 'j1', status: 'queued' }));
    await api.runCopyEdit('p1', { prompt: 'x', keep_sound: false });
    await api.saveCopyEditTemplate('p1', 'Mine 1');
    await api.applyTemplate('p1', 'tpl_a', 'extra');
    await api.applyTemplate('p1', 'tpl_a');
    await api.deleteTemplate('tpl_a');
    const calls = fetchMock.mock.calls.map(([url, init]) => [url, init?.method, init?.body ? JSON.parse(String(init.body)) : undefined]);
    expect(calls).toEqual([
      [`${DEFAULT_BASE_URL}/projects/p1/copy-edit/run`, 'POST', { prompt: 'x', keep_sound: false }],
      [`${DEFAULT_BASE_URL}/projects/p1/copy-edit/template`, 'POST', { name: 'Mine 1' }],
      [`${DEFAULT_BASE_URL}/projects/p1/templates/tpl_a/apply`, 'POST', { prompt: 'extra' }],
      [`${DEFAULT_BASE_URL}/projects/p1/templates/tpl_a/apply`, 'POST', {}],
      [`${DEFAULT_BASE_URL}/templates/tpl_a`, 'DELETE', undefined],
    ]);
  });
});
