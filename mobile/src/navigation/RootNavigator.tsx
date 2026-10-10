import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { DarkTheme, NavigationContainer, type Theme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { AppText } from '../components';
import { CopyEditScreen } from '../screens/CopyEditScreen';
import { EditorRoute } from '../screens/EditorRoute';
import { ExportScreen } from '../screens/ExportScreen';
import { ImportScreen } from '../screens/ImportScreen';
import { ProjectsScreen } from '../screens/ProjectsScreen';
import { ScoreboardScreen } from '../screens/ScoreboardScreen';
import { SettingsScreen } from '../screens/SettingsScreen';
import { TemplatesScreen } from '../screens/TemplatesScreen';
import { colors } from '../theme';
import type { RootStackParamList, TabParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator<TabParamList>();

const navTheme: Theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: colors.accent,
    background: colors.background,
    card: colors.background,
    text: colors.text,
    border: colors.border,
    notification: colors.coral,
  },
};

const tabGlyph: Record<keyof TabParamList, string> = {
  Projects: '▦',
  Templates: '▤',
  Scoreboard: '★',
  Settings: '⚙',
};

function TabsNavigator() {
  return (
    <Tabs.Navigator
      screenOptions={({ route }) => ({
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
        headerShadowVisible: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: { backgroundColor: colors.card, borderTopColor: colors.border },
        tabBarIcon: ({ color }) => (
          <AppText size="lg" color={color}>
            {tabGlyph[route.name]}
          </AppText>
        ),
      })}
    >
      <Tabs.Screen name="Projects" component={ProjectsScreen} options={{ title: 'CutMind' , tabBarLabel: 'Projects' }} />
      <Tabs.Screen name="Templates" component={TemplatesScreen} />
      <Tabs.Screen name="Scoreboard" component={ScoreboardScreen} />
      <Tabs.Screen name="Settings" component={SettingsScreen} />
    </Tabs.Navigator>
  );
}

export function RootNavigator() {
  return (
    <NavigationContainer theme={navTheme}>
      <Stack.Navigator
        screenOptions={{
          headerStyle: { backgroundColor: colors.background },
          headerTintColor: colors.text,
          headerShadowVisible: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Screen name="Tabs" component={TabsNavigator} options={{ headerShown: false }} />
        <Stack.Screen name="Import" component={ImportScreen} options={{ title: 'Import clips' }} />
        <Stack.Screen name="Editor" component={EditorRoute} options={{ title: 'Editor' }} />
        <Stack.Screen name="Export" component={ExportScreen} options={{ title: 'Export' }} />
        <Stack.Screen name="CopyEdit" component={CopyEditScreen} options={{ title: 'Copy an Edit' }} />
        <Stack.Screen name="TemplatesGallery" component={TemplatesScreen} options={{ title: 'Templates' }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
