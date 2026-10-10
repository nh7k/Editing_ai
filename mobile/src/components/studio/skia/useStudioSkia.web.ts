// Web: Skia needs CanvasKit (served from /canvaskit.wasm, see `npm run setup:skia-web`), so the
// drawing components are imported only after it has loaded. Until then callers render fallbacks.
import { LoadSkiaWeb } from '@shopify/react-native-skia/lib/module/web';
import { useEffect, useState } from 'react';

export type StudioSkiaParts = typeof import('./StudioSkiaParts');

let loaded: StudioSkiaParts | null = null;
let loading: Promise<StudioSkiaParts> | null = null;

function load(): Promise<StudioSkiaParts> {
  loading ??= (async () => {
    await LoadSkiaWeb({ locateFile: (file: string) => `/${file}` });
    loaded = await import('./StudioSkiaParts');
    return loaded;
  })();
  return loading;
}

export function useStudioSkia(): StudioSkiaParts | null {
  const [parts, setParts] = useState<StudioSkiaParts | null>(loaded);
  useEffect(() => {
    if (parts) return;
    let alive = true;
    load()
      .then((p) => {
        if (alive) setParts(p);
      })
      .catch(() => {
        // CanvasKit unavailable: keep the plain-view fallbacks.
      });
    return () => {
      alive = false;
    };
  }, [parts]);
  return parts;
}
