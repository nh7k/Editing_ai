import * as ImagePicker from 'expo-image-picker';

import type { UploadFile } from '../api/types';
import { assetsToUploadFiles } from '../screens/ImportScreen';

/** Pick ONE video from the gallery / file picker (web + native), as an upload descriptor; null when cancelled. */
export async function pickOneVideo(): Promise<UploadFile | null> {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ['videos'],
    allowsMultipleSelection: false,
    quality: 1,
  });
  if (result.canceled || result.assets.length === 0) return null;
  return assetsToUploadFiles(result.assets.slice(0, 1))[0] ?? null;
}
