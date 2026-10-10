// Web implementation: no file system or gallery, so use a download link and the Web Share API.
import * as Clipboard from 'expo-clipboard';

export interface MediaActionResult {
  message: string;
}

export async function saveVideo(url: string, fileName: string): Promise<MediaActionResult> {
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.rel = 'noopener';
  a.target = '_blank';
  document.body.appendChild(a);
  a.click();
  a.remove();
  return { message: 'Download started.' };
}

/** Never put the API key into a link that leaves this device. */
export function stripApiKey(url: string): { url: string; hadKey: boolean } {
  try {
    const u = new URL(url);
    const hadKey = u.searchParams.has('api_key');
    u.searchParams.delete('api_key');
    return { url: u.toString(), hadKey };
  } catch {
    return { url, hadKey: false };
  }
}

export async function shareVideo(rawUrl: string, fileName: string, mimeType = 'video/mp4'): Promise<MediaActionResult> {
  const { url, hadKey } = stripApiKey(rawUrl);
  const nav = typeof navigator !== 'undefined' ? navigator : undefined;
  if (nav && typeof nav.share === 'function') {
    try {
      if (hadKey && typeof nav.canShare === 'function') {
        // Protected server: share the video file itself instead of a link that would need the key.
        const blob = await (await fetch(rawUrl)).blob();
        const file = new File([blob], fileName, { type: mimeType });
        if (nav.canShare({ files: [file] })) {
          await nav.share({ title: 'CutMind video', files: [file] });
          return { message: 'Shared.' };
        }
      }
      await nav.share({ title: 'CutMind video', url });
      return { message: 'Shared.' };
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') return { message: 'Share cancelled.' };
      // Fall through to copying the link.
    }
  }
  await Clipboard.setStringAsync(url);
  return {
    message: hadKey
      ? 'Link copied (without your API key — viewers need access to your CutMind server).'
      : 'Link copied to clipboard.',
  };
}
