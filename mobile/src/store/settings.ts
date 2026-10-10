import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSyncExternalStore } from 'react';

/** In a browser opened from another device (phone on the same Wi-Fi: http://<laptop-ip>:8081), "localhost" would be
 * the phone itself — the backend is on the machine that served the page, port 8000. */
function defaultBaseUrl(): string {
  const loc = typeof window !== 'undefined' ? window.location : undefined;
  if (loc && loc.hostname && !['localhost', '127.0.0.1', ''].includes(loc.hostname)) {
    return `${loc.protocol}//${loc.hostname}:8000`;
  }
  return 'http://localhost:8000';
}

export const DEFAULT_BASE_URL = defaultBaseUrl();
const STORAGE_KEY = 'cutmind.settings.v1';

export interface SettingsState {
  baseUrl: string;
  /** Optional API key sent as `X-API-Key` when the backend sets CUTMIND_API_KEY. '' = none. */
  apiKey: string;
  loaded: boolean;
}

let state: SettingsState = { baseUrl: DEFAULT_BASE_URL, apiKey: '', loaded: false };
const listeners = new Set<() => void>();

function emit(next: SettingsState) {
  state = next;
  listeners.forEach((l) => l());
}

/** Trim whitespace, add http:// when no scheme is given, drop trailing slashes. */
export function normalizeBaseUrl(input: string): string {
  let url = input.trim();
  if (!url) return DEFAULT_BASE_URL;
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`;
  return url.replace(/\/+$/, '');
}

export function isValidBaseUrl(input: string): boolean {
  return /^https?:\/\/[^\s/]+(:\d+)?(\/[^\s]*)?$/i.test(normalizeBaseUrl(input));
}

export function getBaseUrl(): string {
  return state.baseUrl;
}

export function getApiKey(): string {
  return state.apiKey;
}

export function getSettings(): SettingsState {
  return state;
}

export async function loadSettings(): Promise<SettingsState> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<SettingsState> | null;
      if (parsed && typeof parsed === 'object') {
        // Older versions stored only {baseUrl}; a missing apiKey means "no key".
        const baseUrl =
          typeof parsed.baseUrl === 'string' && parsed.baseUrl ? normalizeBaseUrl(parsed.baseUrl) : state.baseUrl;
        const apiKey = typeof parsed.apiKey === 'string' ? parsed.apiKey.trim() : '';
        emit({ baseUrl, apiKey, loaded: true });
        return state;
      }
    }
  } catch {
    // Corrupt or unavailable storage: keep defaults.
  }
  emit({ ...state, loaded: true });
  return state;
}

function persist(): Promise<void> {
  return AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ baseUrl: state.baseUrl, apiKey: state.apiKey }));
}

export async function setBaseUrl(url: string): Promise<void> {
  const baseUrl = normalizeBaseUrl(url);
  emit({ ...state, baseUrl });
  await persist();
}

/** Store the API key (trimmed). An empty string disables the header. */
export async function setApiKey(key: string): Promise<void> {
  emit({ ...state, apiKey: key.trim() });
  await persist();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useSettings(): SettingsState {
  return useSyncExternalStore(subscribe, getSettings, getSettings);
}
