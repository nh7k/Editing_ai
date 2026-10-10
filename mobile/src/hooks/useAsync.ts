import { useCallback, useEffect, useRef, useState } from 'react';

import { errorMessage } from '../api/client';

export interface AsyncState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
  /** Re-run the loader. `asRefresh` shows the pull-to-refresh spinner instead of the full loader. */
  reload: (asRefresh?: boolean) => Promise<void>;
  setData: (updater: (prev: T | undefined) => T | undefined) => void;
}

interface InternalState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
}

/**
 * Small data-loading hook with loading / refreshing / error state.
 * The loader runs on mount and whenever `key` changes.
 */
export function useAsync<T>(loader: () => Promise<T>, key: string = ''): AsyncState<T> {
  const [state, setState] = useState<InternalState<T>>({
    data: undefined,
    error: null,
    loading: true,
    refreshing: false,
  });
  const loaderRef = useRef(loader);
  const requestId = useRef(0);
  const mounted = useRef(false);

  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback((id: number) => {
    return loaderRef.current().then(
      (data) => {
        if (!mounted.current || id !== requestId.current) return;
        setState({ data, error: null, loading: false, refreshing: false });
      },
      (e: unknown) => {
        if (!mounted.current || id !== requestId.current) return;
        setState((s) => ({ ...s, error: errorMessage(e), loading: false, refreshing: false }));
      },
    );
  }, []);

  useEffect(() => {
    const id = ++requestId.current;
    void run(id);
  }, [key, run]);

  const reload = useCallback(
    async (asRefresh = false) => {
      const id = ++requestId.current;
      setState((s) => ({ ...s, loading: asRefresh ? s.loading : true, refreshing: asRefresh }));
      await run(id);
    },
    [run],
  );

  const setData = useCallback((updater: (prev: T | undefined) => T | undefined) => {
    setState((s) => ({ ...s, data: updater(s.data) }));
  }, []);

  return { ...state, reload, setData };
}
