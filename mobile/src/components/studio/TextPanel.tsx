import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { api, errorMessage } from '../../api/client';
import type { ManualOp, PlanText, TextStylesResponse } from '../../api/types';
import { AppText } from '../AppText';
import { studio } from './theme';

export interface TextPanelProps {
  /** 'text' = add a new text / label; 'captions' = restyle the captions of the current edit. */
  mode: 'text' | 'captions';
  /** Apply changes directly (no AI). */
  onApply: (ops: ManualOp[], label: string) => void;
  busy?: boolean;
  /** Text items of the current plan (indexes match `update_text`); captions are not listed. */
  texts?: PlanText[];
}

type Track = 'none' | 'person' | 'face';
const POSITIONS = ['top', 'center', 'bottom'] as const;

function Chip({ label, on, onPress, testID, color }: { label: string; on: boolean; onPress: () => void; testID: string; color?: string }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }} testID={testID}
      style={[styles.chip, on && styles.chipOn, color ? { borderColor: color } : null]}>
      {color ? <View style={[styles.dot, { backgroundColor: color }]} /> : null}
      <AppText size="xs" weight="semibold" color={on ? studio.white : studio.muted}>
        {label}
      </AppText>
    </Pressable>
  );
}

/** Manual text editor: fonts, presets, colours, animations, position, and text that follows a person. */
export function TextPanel({ mode, onApply, busy, texts }: TextPanelProps) {
  const [data, setData] = useState<TextStylesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [preset, setPreset] = useState<string | null>(null);
  const [font, setFont] = useState<string | null>(null);
  const [color, setColor] = useState<string | null>(null);
  const [anim, setAnim] = useState<string | null>(null);
  const [position, setPosition] = useState<(typeof POSITIONS)[number]>('top');
  const [track, setTrack] = useState<Track>('none');
  const [behind, setBehind] = useState(false);
  /** Index (in the plan's text list) of the text being changed; null = add a new text. */
  const [selected, setSelected] = useState<number | null>(null);
  const editable = (texts ?? []).map((t, index) => ({ t, index })).filter(({ t }) => t.kind !== 'caption');
  const selectedItem = selected !== null ? texts?.[selected] : undefined;

  useEffect(() => {
    let alive = true;
    api
      .getTextStyles()
      .then((r) => alive && setData(r))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, []);

  const look = {
    ...(preset ? { preset } : {}),
    ...(font ? { font } : {}),
    ...(color ? { color } : {}),
    ...(anim ? { animation: anim } : {}),
  };
  const canAdd =
    mode === 'captions' ? Object.keys(look).length > 0 : selectedItem ? true : text.trim().length > 0;

  const apply = () => {
    if (!canAdd || busy) return;
    if (mode === 'captions') {
      onApply([{ op: 'style_captions', ...look }], `Captions: ${Object.values(look).join(', ')}`);
    } else if (selected !== null && selectedItem) {
      const newText = text.trim();
      onApply([{ op: 'update_text', index: selected, ...(newText ? { text: newText } : {}), behind, ...look }],
        `Text “${newText || selectedItem.text}”${behind ? ' behind the person' : ''}`);
      setText('');
    } else {
      onApply([{ op: 'add_text', text: text.trim(), position, track, ...(behind ? { behind } : {}), ...look }],
        `Text “${text.trim()}”${track !== 'none' ? ` follows the ${track}` : ''}${behind ? ' behind the person' : ''}`);
      setText('');
    }
  };

  return (
    <View style={styles.panel} testID={`text-panel-${mode}`}>
      <AppText size="md" weight="semibold">
        {mode === 'captions' ? 'Caption style' : 'Text'}
      </AppText>
      <AppText size="xs" color={studio.muted}>
        Applied directly — no AI step. Text-only changes reuse the cut, so they render in seconds.
      </AppText>
      {!data && !error ? <ActivityIndicator color={studio.blue} /> : null}
      {error ? (
        <AppText size="xs" color={studio.red} testID="text-styles-error">
          Could not load text styles: {error}
        </AppText>
      ) : null}
      {data ? (
        <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
          {mode === 'text' && editable.length ? (
            <>
              <AppText size="xs" weight="semibold" color={studio.muted}>Change a text of this edit</AppText>
              <View style={styles.wrap}>
                {editable.map(({ t, index }) => (
                  <Chip key={index} label={t.text.length > 18 ? `${t.text.slice(0, 18)}…` : t.text} on={selected === index}
                    testID={`text-item-${index}`} onPress={() => {
                      const next = selected === index ? null : index;
                      setSelected(next);
                      setBehind(next !== null ? !!texts?.[next]?.behind : false);
                    }} />
                ))}
              </View>
            </>
          ) : null}
          {mode === 'text' ? (
            <TextInput value={text} onChangeText={setText}
              placeholder={selectedItem ? `New words for “${selectedItem.text}” (optional)…` : 'Type your text (e.g. RIYA, Goa 2026)…'}
              placeholderTextColor={studio.faint} style={styles.input} testID="text-input" maxLength={60} />
          ) : null}
          {mode === 'text' ? (
            <Pressable onPress={() => setBehind((b) => !b)} accessibilityRole="switch" accessibilityState={{ checked: behind }}
              testID="text-behind-toggle" style={styles.toggleRow}>
              <View style={[styles.toggle, behind && styles.toggleOn]}>
                <View style={[styles.knob, behind && styles.knobOn]} />
              </View>
              <View style={styles.flex}>
                <AppText size="xs" weight="semibold">Behind person</AppText>
                <AppText size="xs" color={studio.muted}>Text sits behind the people in the shot.</AppText>
              </View>
            </Pressable>
          ) : null}
          <AppText size="xs" weight="semibold" color={studio.muted}>Style</AppText>
          <View style={styles.wrap}>
            {data.presets.map((p) => (
              <Chip key={p.id} label={p.name} on={preset === p.id} color={p.color} testID={`preset-${p.id}`}
                onPress={() => setPreset(preset === p.id ? null : p.id)} />
            ))}
          </View>
          <AppText size="xs" weight="semibold" color={studio.muted}>Font</AppText>
          <View style={styles.wrap}>
            {data.fonts.map((f) => (
              <Chip key={f.id} label={f.family} on={font === f.id} testID={`font-${f.id}`}
                onPress={() => setFont(font === f.id ? null : f.id)} />
            ))}
          </View>
          <AppText size="xs" weight="semibold" color={studio.muted}>Colour</AppText>
          <View style={styles.wrap}>
            {data.colors.filter((c, i, all) => all.findIndex((x) => x.hex === c.hex) === i).map((c) => (
              <Chip key={c.hex} label={c.word} on={color === c.hex} color={c.hex} testID={`color-${c.word}`}
                onPress={() => setColor(color === c.hex ? null : c.hex)} />
            ))}
          </View>
          <AppText size="xs" weight="semibold" color={studio.muted}>Animation</AppText>
          <View style={styles.wrap}>
            {data.animations.map((a) => (
              <Chip key={a.id} label={a.id.replace(/_/g, ' ')} on={anim === a.id} testID={`anim-${a.id}`}
                onPress={() => setAnim(anim === a.id ? null : a.id)} />
            ))}
          </View>
          {mode === 'text' ? (
            <>
              <AppText size="xs" weight="semibold" color={studio.muted}>Position</AppText>
              <View style={styles.wrap}>
                {POSITIONS.map((p) => (
                  <Chip key={p} label={p} on={position === p} testID={`pos-${p}`} onPress={() => setPosition(p)} />
                ))}
              </View>
              <AppText size="xs" weight="semibold" color={studio.muted}>Follow someone</AppText>
              <View style={styles.wrap}>
                {(['none', 'person', 'face'] as Track[]).map((t) => (
                  <Chip key={t} label={t === 'none' ? 'stay in place' : `follow the ${t}`} on={track === t}
                    testID={`track-${t}`} onPress={() => setTrack(t)} />
                ))}
              </View>
            </>
          ) : (
            <Pressable onPress={() => onApply([{ op: 'remove_captions' }], 'Remove captions')} testID="remove-captions"
              accessibilityRole="button" style={styles.ghost}>
              <AppText size="xs" color={studio.red}>Remove all captions</AppText>
            </Pressable>
          )}
        </ScrollView>
      ) : null}
      <Pressable onPress={apply} disabled={!canAdd || busy} accessibilityRole="button" testID="text-apply"
        accessibilityState={{ disabled: !canAdd || busy }} style={[styles.apply, (!canAdd || busy) && styles.applyOff]}>
        <AppText size="sm" weight="semibold" color={studio.white}>
          {mode === 'captions' ? '⚡ Apply to captions' : selectedItem ? '⚡ Update text' : '⚡ Add text'}
        </AppText>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { width: 340, backgroundColor: studio.panel, borderRadius: 16, borderWidth: 1, borderColor: studio.border, padding: 14, gap: 8 },
  scroll: { flex: 1 },
  content: { gap: 8, paddingBottom: 8 },
  input: { backgroundColor: studio.card, borderRadius: 10, borderWidth: 1, borderColor: studio.border, color: studio.text,
    paddingHorizontal: 10, height: 36, fontSize: 13 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: 999, paddingHorizontal: 9, paddingVertical: 4,
    borderWidth: 1, borderColor: studio.border },
  chipOn: { backgroundColor: studio.blue, borderColor: studio.blue },
  dot: { width: 8, height: 8, borderRadius: 4 },
  ghost: { paddingVertical: 6 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 2 },
  toggle: { width: 34, height: 20, borderRadius: 10, backgroundColor: studio.card, borderWidth: 1, borderColor: studio.border,
    padding: 2, justifyContent: 'center' },
  toggleOn: { backgroundColor: studio.blue, borderColor: studio.blue },
  knob: { width: 14, height: 14, borderRadius: 7, backgroundColor: studio.muted },
  knobOn: { backgroundColor: studio.white, alignSelf: 'flex-end' },
  flex: { flex: 1 },
  apply: { backgroundColor: studio.violet, borderRadius: 10, paddingVertical: 10, alignItems: 'center' },
  applyOff: { opacity: 0.45 },
});
