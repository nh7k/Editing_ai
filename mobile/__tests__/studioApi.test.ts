import { api } from '../src/api/client';
import { DEFAULT_BASE_URL, setApiKey } from '../src/store/settings';

type FetchMock = jest.Mock<Promise<Response>, [RequestInfo | URL, RequestInit | undefined]>;

function mockResponse(status: number, body: unknown): Response {
  const text = JSON.stringify(body);
  return { ok: status >= 200 && status < 300, status, text: () => Promise.resolve(text) } as unknown as Response;
}

describe('studio api endpoints', () => {
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

  it('outputUrl adds variant and format, keeping the old signature working', () => {
    const base = `${DEFAULT_BASE_URL}/projects/p1/output`;
    expect(api.outputUrl('p1', 'j1')).toBe(`${base}?v=j1`);
    expect(api.outputUrl('p1', 'j1', 'mp4', 2)).toBe(`${base}?v=j1&variant=2`);
    expect(api.outputUrl('p1', 'j1', 'gif', 0)).toBe(`${base}?v=j1&variant=0&format=gif`);
    expect(api.outputUrl('p1', null, 'mp3', 1)).toBe(`${base}?variant=1&format=mp3`);
    expect(api.outputUrl('p1', 'j1', 'mp4', null)).toBe(`${base}?v=j1`);
  });

  it('media URLs carry api_key after variant / format / frames', async () => {
    await setApiKey('k&1');
    expect(api.outputUrl('p1', 'j1', 'gif', 1)).toBe(
      `${DEFAULT_BASE_URL}/projects/p1/output?v=j1&variant=1&format=gif&api_key=k%261`,
    );
    expect(api.filmstripUrl('p1', 'c 1')).toBe(
      `${DEFAULT_BASE_URL}/projects/p1/clips/c%201/filmstrip?frames=10&api_key=k%261`,
    );
    expect(api.filmstripUrl('p1', 'c1', 6)).toBe(`${DEFAULT_BASE_URL}/projects/p1/clips/c1/filmstrip?frames=6&api_key=k%261`);
  });

  it('filmstripUrl without a key has no api_key param', () => {
    expect(api.filmstripUrl('p1', 'c1')).toBe(`${DEFAULT_BASE_URL}/projects/p1/clips/c1/filmstrip?frames=10`);
  });

  it('chooseVariant POSTs {variant} to /jobs/{id}/choose with the API key header', async () => {
    await setApiKey('s3cret');
    fetchMock.mockResolvedValueOnce(mockResponse(200, { ok: true, chosen: 2 }));
    const res = await api.chooseVariant('j1', 2);
    expect(res).toEqual({ ok: true, chosen: 2 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${DEFAULT_BASE_URL}/jobs/j1/choose`);
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ variant: 2 });
    expect((init?.headers as Record<string, string>)['X-API-Key']).toBe('s3cret');
  });

  it('getWaveform GETs the waveform with points', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { peaks: [0, 0.5, 1], duration: 3 }));
    const w = await api.getWaveform('p1', 'c1', 200);
    expect(w).toEqual({ peaks: [0, 0.5, 1], duration: 3 });
    expect(fetchMock.mock.calls[0][0]).toBe(`${DEFAULT_BASE_URL}/projects/p1/clips/c1/waveform?points=200`);
  });

  it('listStyles GETs /styles', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { styles: [] }));
    expect(await api.listStyles()).toEqual({ styles: [] });
    expect(fetchMock.mock.calls[0][0]).toBe(`${DEFAULT_BASE_URL}/styles`);
  });

  it('startEdit sends variations and style', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(202, { job_id: 'j2', status: 'queued' }));
    await api.startEdit('p1', { prompt: 'go', variations: 3, style: 'cyan_kinetic' });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      prompt: 'go',
      variations: 3,
      style: 'cyan_kinetic',
    });
  });

  it('surfaces the {"error":{code,message}} shape from choose', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(400, { error: { code: 'bad_variant', message: 'No such variant' } }));
    await expect(api.chooseVariant('j1', 9)).rejects.toMatchObject({ code: 'bad_variant', message: 'No such variant' });
  });
  it('getFxCatalog GETs /fx with the API key header', async () => {
    await setApiKey('k1');
    const body = { catalog: { video_effect: [{ id: 'glitch', name: 'Glitch', description: 'Digital glitch' }] }, counts: { video_effect: 1 } };
    fetchMock.mockResolvedValueOnce(mockResponse(200, body));
    expect(await api.getFxCatalog()).toEqual(body);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${DEFAULT_BASE_URL}/fx`);
    expect(init?.method).toBe('GET');
    expect((init?.headers as Record<string, string>)['X-API-Key']).toBe('k1');
  });

  it('getProjectMemory GETs /projects/{id}/memory (id encoded)', async () => {
    const body = { history: [], preferences: { edits_remembered: 0 }, summary: '' };
    fetchMock.mockResolvedValueOnce(mockResponse(200, body));
    expect(await api.getProjectMemory('p 1')).toEqual(body);
    expect(fetchMock.mock.calls[0][0]).toBe(`${DEFAULT_BASE_URL}/projects/p%201/memory`);
  });

  it('getFxCatalog / getProjectMemory surface backend error codes', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(500, { error: { code: 'fx_unavailable', message: 'Catalog broken' } }));
    await expect(api.getFxCatalog()).rejects.toMatchObject({ code: 'fx_unavailable', message: 'Catalog broken', status: 500 });
    fetchMock.mockResolvedValueOnce(mockResponse(404, { error: { code: 'project_not_found', message: 'No such project' } }));
    await expect(api.getProjectMemory('nope')).rejects.toMatchObject({ code: 'project_not_found', status: 404 });
  });
});
