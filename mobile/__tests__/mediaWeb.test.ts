import * as Clipboard from 'expo-clipboard';

import { shareVideo, stripApiKey } from '../src/utils/media.web';

jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn(async () => true) }));

describe('web share never leaks the API key', () => {
  it('strips api_key and keeps other params', () => {
    expect(stripApiKey('http://h:8000/projects/p/output?v=j1&api_key=secret')).toEqual({
      url: 'http://h:8000/projects/p/output?v=j1',
      hadKey: true,
    });
    expect(stripApiKey('http://h/x?v=1').hadKey).toBe(false);
  });

  it('copies a link without the key when Web Share is unavailable', async () => {
    const res = await shareVideo('http://h:8000/projects/p/output?api_key=secret', 'a.mp4');
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith('http://h:8000/projects/p/output');
    expect(res.message).toMatch(/without your API key/);
  });
});
