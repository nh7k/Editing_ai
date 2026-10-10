// Import only the four weights we use so the other Inter files are not bundled.
import { Inter_400Regular } from '@expo-google-fonts/inter/400Regular';
import { Inter_500Medium } from '@expo-google-fonts/inter/500Medium';
import { Inter_600SemiBold } from '@expo-google-fonts/inter/600SemiBold';
import { Inter_700Bold } from '@expo-google-fonts/inter/700Bold';
import { useFonts } from 'expo-font';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { FontsLoadedContext } from './src/components/FontContext';
import { RootNavigator } from './src/navigation/RootNavigator';
import { loadSettings, useSettings } from './src/store/settings';
import { colors } from './src/theme';

export default function App() {
  // Until Inter is loaded (or if loading fails) text renders with the system font.
  const [fontsLoaded] = useFonts({ Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold });

  const settings = useSettings();

  useEffect(() => {
    void loadSettings();
  }, []);

  return (
    <GestureHandlerRootView style={styles.root}>
      <SafeAreaProvider>
        <FontsLoadedContext.Provider value={fontsLoaded}>
          <StatusBar style="light" />
          {settings.loaded ? (
            <RootNavigator />
          ) : (
            <View style={styles.boot}>
              <ActivityIndicator color={colors.accent} />
            </View>
          )}
        </FontsLoadedContext.Provider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  boot: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.background },
});
