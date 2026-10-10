import { useLayoutEffect } from 'react';

import { useIsWideLayout } from '../hooks/useIsWideLayout';
import type { RootScreenProps } from '../navigation/types';
import { EditorScreen } from './EditorScreen';
import { StudioEditor } from './StudioEditor';

type Props = RootScreenProps<'Editor'>;

/** Editor route: the desktop studio on wide windows (≥ 1024 px), the mobile editor otherwise. */
export function EditorRoute(props: Props) {
  const wide = useIsWideLayout();
  const { navigation } = props;
  useLayoutEffect(() => {
    // The studio draws its own top bar.
    navigation.setOptions({ headerShown: !wide });
  }, [navigation, wide]);
  return wide ? <StudioEditor {...props} /> : <EditorScreen {...props} />;
}
