import { useCallback, useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';

import { api, errorMessage } from '../api/client';

export type VoiceState = 'idle' | 'recording' | 'transcribing';

const MAX_SECONDS = 45;

/** Browser support for recording (web build only; native recording is not wired up yet). */
export function voiceSupported(): boolean {
  return (
    Platform.OS === 'web' &&
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof (globalThis as { MediaRecorder?: unknown }).MediaRecorder !== 'undefined'
  );
}

/**
 * Tap once to start recording, tap again to stop. The audio goes to the backend's local Whisper
 * (POST /transcribe, speech in any language → English) and `onText` receives the prompt.
 */
export function useVoicePrompt(onText: (text: string) => void) {
  const [state, setState] = useState<VoiceState>('idle');
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onTextRef = useRef(onText);
  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop();
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (!voiceSupported()) {
      setError('Voice input works in the web app for now.');
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError('Microphone permission was denied.');
      return;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    recorder.current = rec;
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
      if (blob.size === 0) {
        setState('idle');
        return;
      }
      setState('transcribing');
      try {
        const { text } = await api.transcribeVoice(blob, rec.mimeType.includes('mp4') ? 'voice.m4a' : 'voice.webm');
        if (text.trim()) onTextRef.current(text.trim());
        else setError("Didn't catch that — try again a little louder.");
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setState('idle');
      }
    };
    rec.start();
    setState('recording');
    timer.current = setTimeout(stop, MAX_SECONDS * 1000);
  }, [stop]);

  const toggle = useCallback(() => {
    if (state === 'recording') stop();
    else if (state === 'idle') void start();
  }, [state, start, stop]);

  useEffect(() => stop, [stop]);

  return { state, error, toggle };
}
