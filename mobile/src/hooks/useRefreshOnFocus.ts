import { useEffect, useRef } from 'react';

interface FocusEmitter {
  addListener: (event: 'focus' | 'blur', cb: () => void) => () => void;
}

/** Calls `refresh` when the screen regains focus after having been left (not on the first focus). */
export function useRefreshOnFocus(navigation: FocusEmitter, refresh: () => void): void {
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  });

  useEffect(() => {
    let wasBlurred = false;
    const offBlur = navigation.addListener('blur', () => {
      wasBlurred = true;
    });
    const offFocus = navigation.addListener('focus', () => {
      if (!wasBlurred) return;
      wasBlurred = false;
      refreshRef.current();
    });
    return () => {
      offBlur();
      offFocus();
    };
  }, [navigation]);
}
