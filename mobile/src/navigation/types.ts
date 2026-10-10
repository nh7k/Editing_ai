import type { BottomTabScreenProps } from '@react-navigation/bottom-tabs';
import type { CompositeScreenProps, NavigatorScreenParams } from '@react-navigation/native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';

export type TabParamList = {
  Projects: undefined;
  Templates: undefined;
  Scoreboard: undefined;
  Settings: undefined;
};

export type RootStackParamList = {
  Tabs: NavigatorScreenParams<TabParamList> | undefined;
  Import: { projectId: string; projectName?: string };
  /**
   * `jobId` hands the editor a job that was started elsewhere (Copy an Edit / Templates): the editor shows the
   * live view for it. `jobLabel` is the chat text for that job (studio).
   */
  Editor: { projectId: string; projectName?: string; jobId?: string; jobLabel?: string };
  CopyEdit: { projectId: string; projectName?: string };
  /** The template gallery opened from the editor (the project is preselected). */
  TemplatesGallery: { projectId?: string; projectName?: string };
  Export: { projectId: string; projectName?: string };
};

export type RootScreenProps<T extends keyof RootStackParamList> = NativeStackScreenProps<RootStackParamList, T>;

export type TabScreenProps<T extends keyof TabParamList> = CompositeScreenProps<
  BottomTabScreenProps<TabParamList, T>,
  NativeStackScreenProps<RootStackParamList>
>;
