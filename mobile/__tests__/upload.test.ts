import { Platform } from 'react-native';

import { api, ApiError } from '../src/api/client';
import { DEFAULT_BASE_URL, setApiKey } from '../src/store/settings';
import { clipA } from './fixtures';

/** Minimal fake XMLHttpRequest that records what the client sends. */
class FakeXHR {
  static last: FakeXHR | null = null;
  method = '';
  url = '';
  headers: Record<string, string> = {};
  body: unknown;
  status = 0;
  responseText = '';
  timeout = 0;
  upload: { onprogress: ((ev: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  constructor() {
    FakeXHR.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  send(body: unknown) {
    this.body = body;
  }
  respond(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }
}

describe('api.uploadClips (native FormData)', () => {
  const original = globalThis.XMLHttpRequest;
  beforeEach(() => {
    globalThis.XMLHttpRequest = FakeXHR as unknown as typeof XMLHttpRequest;
  });
  afterEach(() => {
    globalThis.XMLHttpRequest = original;
  });

  const file = { uri: 'file:///clip.mp4', name: 'clip.mp4', type: 'video/mp4' };

  it('posts multipart field "files", reports progress and resolves clips', async () => {
    const onProgress = jest.fn();
    const append = jest.spyOn(FormData.prototype, 'append');
    const pending = api.uploadClips('p1', [file, { ...file, name: 'b.mp4' }], onProgress);
    await new Promise((r) => setTimeout(r, 0));
    const xhr = FakeXHR.last!;
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe(`${DEFAULT_BASE_URL}/projects/p1/clips`);
    expect(xhr.body).toBeInstanceOf(FormData);
    // React Native FormData takes {uri, name, type} descriptors for files.
    expect(append.mock.calls).toEqual([
      ['files', file],
      ['files', { ...file, name: 'b.mp4' }],
    ]);
    append.mockRestore();

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
    expect(onProgress).toHaveBeenCalledWith({ loaded: 50, total: 100, fraction: 0.5 });

    xhr.respond(200, { clips: [clipA] });
    await expect(pending).resolves.toEqual({ clips: [clipA] });
  });

  it('does not set X-API-Key without a key', async () => {
    const pending = api.uploadClips('p1', [file]);
    await new Promise((r) => setTimeout(r, 0));
    expect(FakeXHR.last!.headers).not.toHaveProperty('X-API-Key');
    FakeXHR.last!.respond(200, { clips: [] });
    await pending;
  });

  it('sets the X-API-Key header when a key is set, and maps 401', async () => {
    await setApiKey('s3cret');
    try {
      const pending = api.uploadClips('p1', [file]);
      await new Promise((r) => setTimeout(r, 0));
      expect(FakeXHR.last!.headers['X-API-Key']).toBe('s3cret');
      FakeXHR.last!.respond(401, { error: { code: 'unauthorized', message: 'Missing or wrong API key.' } });
      const err = (await pending.catch((e: unknown) => e)) as ApiError;
      expect(err.code).toBe('unauthorized');
      expect(err.message).toContain('API key in Settings');
    } finally {
      await setApiKey('');
    }
  });

  it('parses error bodies (e.g. 413 too big)', async () => {
    const pending = api.uploadClips('p1', [file]);
    await new Promise((r) => setTimeout(r, 0));
    FakeXHR.last!.respond(413, { error: { code: 'file_too_large', message: 'Max 500 MB' } });
    const err = (await pending.catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('file_too_large');
    expect(err.status).toBe(413);
  });

  it('on web appends the picked File/Blob with its file name', async () => {
    jest.replaceProperty(Platform, 'OS', 'web');
    const append = jest.spyOn(FormData.prototype, 'append').mockImplementation(() => undefined);
    const blob = new Blob(['abc'], { type: 'video/mp4' });
    const pending = api.uploadClips('p1', [{ ...file, uri: 'blob:x', file: blob }]);
    await new Promise((r) => setTimeout(r, 0));
    expect(append).toHaveBeenCalledWith('files', blob, 'clip.mp4');
    FakeXHR.last!.respond(200, { clips: [] });
    await expect(pending).resolves.toEqual({ clips: [] });
    jest.restoreAllMocks();
  });
});
