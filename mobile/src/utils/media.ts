// Native implementation (Android / iOS). The web variant lives in media.web.ts.
import { Directory, File, Paths } from 'expo-file-system';
import * as MediaLibrary from 'expo-media-library';
import * as Sharing from 'expo-sharing';

export interface MediaActionResult {
  message: string;
}

async function downloadToCache(url: string, fileName: string): Promise<File> {
  const dir = new Directory(Paths.cache, 'exports');
  if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
  const target = new File(dir, fileName);
  if (target.exists) target.delete();
  return File.downloadFileAsync(url, target);
}

/** Download the rendered video and save it to the device gallery. */
export async function saveVideo(url: string, fileName: string): Promise<MediaActionResult> {
  const perm = await MediaLibrary.requestPermissionsAsync(true);
  if (!perm.granted) {
    throw new Error('Permission to save to your library was denied.');
  }
  const file = await downloadToCache(url, fileName);
  await MediaLibrary.Asset.create(file.uri);
  return { message: 'Saved to your gallery.' };
}

/**
 * Download the rendered file and open the system share sheet.
 * `mimeType` defaults to mp4; pass `image/gif` / `audio/mpeg` for the gif / mp3 extras.
 */
export async function shareVideo(url: string, fileName: string, mimeType = 'video/mp4'): Promise<MediaActionResult> {
  if (!(await Sharing.isAvailableAsync())) {
    throw new Error('Sharing is not available on this device.');
  }
  const file = await downloadToCache(url, fileName);
  await Sharing.shareAsync(file.uri, {
    mimeType,
    dialogTitle: mimeType === 'video/mp4' ? 'Share your CutMind video' : 'Share your CutMind export',
  });
  return { message: 'Shared.' };
}
