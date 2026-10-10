import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  getApiKey,
  getBaseUrl,
  isValidBaseUrl,
  loadSettings,
  normalizeBaseUrl,
  setApiKey,
  setBaseUrl,
} from '../src/store/settings';

const KEY = 'cutmind.settings.v1';

async function stored(): Promise<unknown> {
  return JSON.parse((await AsyncStorage.getItem(KEY)) ?? 'null');
}

describe('settings store', () => {
  afterEach(async () => {
    await setApiKey('');
    await AsyncStorage.clear();
  });

  it('normalises backend URLs', () => {
    expect(normalizeBaseUrl(' http://10.0.2.2:8000/ ')).toBe('http://10.0.2.2:8000');
    expect(normalizeBaseUrl('192.168.1.20:8000')).toBe('http://192.168.1.20:8000');
    expect(normalizeBaseUrl('')).toBe('http://localhost:8000');
    expect(isValidBaseUrl('http://192.168.1.20:8000')).toBe(true);
    expect(isValidBaseUrl('http://bad url')).toBe(false);
  });

  it('persists the URL and loads it back', async () => {
    await setBaseUrl('http://10.0.2.2:8000/');
    expect(getBaseUrl()).toBe('http://10.0.2.2:8000');
    expect(await stored()).toEqual({ baseUrl: 'http://10.0.2.2:8000', apiKey: '' });
    const loaded = await loadSettings();
    expect(loaded).toEqual({ baseUrl: 'http://10.0.2.2:8000', apiKey: '', loaded: true });
  });

  it('persists the API key (trimmed) next to the URL and loads it back', async () => {
    await setBaseUrl('http://10.0.2.2:8000');
    await setApiKey('  s3cret \n');
    expect(getApiKey()).toBe('s3cret');
    expect(await stored()).toEqual({ baseUrl: 'http://10.0.2.2:8000', apiKey: 's3cret' });

    await AsyncStorage.setItem(KEY, JSON.stringify({ baseUrl: 'http://10.0.2.2:8000', apiKey: 'other' }));
    const loaded = await loadSettings();
    expect(loaded).toEqual({ baseUrl: 'http://10.0.2.2:8000', apiKey: 'other', loaded: true });
    expect(getApiKey()).toBe('other');
  });

  it('loads the old {baseUrl}-only format with an empty API key', async () => {
    await setApiKey('stale');
    await AsyncStorage.setItem(KEY, JSON.stringify({ baseUrl: 'http://192.168.1.20:8000/' }));
    const loaded = await loadSettings();
    expect(loaded).toEqual({ baseUrl: 'http://192.168.1.20:8000', apiKey: '', loaded: true });
    expect(getApiKey()).toBe('');
  });
});
