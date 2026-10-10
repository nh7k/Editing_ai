import { createContext, useContext } from 'react';

/** True once the Inter font files are loaded; until then we render with the system font. */
export const FontsLoadedContext = createContext(false);

export function useFontsReady(): boolean {
  return useContext(FontsLoadedContext);
}
