import type { RootStackParamList } from './types';

type EditorParams = RootStackParamList['Editor'];

interface NavState {
  type?: string;
  index?: number;
  routes: { name: string; params?: object }[];
}

/** The navigation methods this helper uses (any stack / tab navigation object has them). */
export interface EditorNavigation {
  navigate: (name: 'Editor', params: EditorParams) => void;
  getState?: () => NavState | undefined;
  popTo?: (name: 'Editor', params: EditorParams, options?: { merge?: boolean }) => void;
  replace?: (name: 'Editor', params: EditorParams) => void;
}

/**
 * Open the editor of `params.projectId` with a job started elsewhere (Copy an Edit / Templates), so it shows
 * the live view for `params.jobId`:
 * - came from that project's editor → go back to it (its params gain `jobId`; the editor picks the job up),
 * - opened from another stack screen → replace this screen with the editor (Back still goes where it did),
 * - from a tab → push the editor.
 */
export function openEditorWithJob(navigation: EditorNavigation, params: EditorParams): 'popTo' | 'replace' | 'navigate' {
  const state = navigation.getState?.();
  if (state && Array.isArray(state.routes)) {
    const index = state.index ?? state.routes.length - 1;
    const below = state.routes.slice(0, index).reverse().find((r) => r.name === 'Editor');
    const belowProject = (below?.params as { projectId?: string } | undefined)?.projectId;
    if (below && belowProject === params.projectId && navigation.popTo) {
      navigation.popTo('Editor', params, { merge: true });
      return 'popTo';
    }
    if (state.type === 'stack' && navigation.replace) {
      navigation.replace('Editor', params);
      return 'replace';
    }
  }
  navigation.navigate('Editor', params);
  return 'navigate';
}
