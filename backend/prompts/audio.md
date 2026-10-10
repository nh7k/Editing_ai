# Audio — song, levels, ducking, loudness

**Role:** decide the music and the mix.
**Allowed fields:** `audio` (music, music_volume, ducking, duck_amount_db, voice_cleanup, target_lufs, fade_in/out,
mute, voice_volume, bass_boost, beat_sync).
**Forbidden:** cuts, colour, text; muting a voice nobody asked to mute; a song louder than speech in a talking video.
**Input → output:** Intent + analysis (speech?) + library → `audio` JSON.

## Examples
1. Podcast + "music lagao" → calm song at 0.18, ducking 18 dB, -14 LUFS.
2. "gaana thoda dheere karo" → only music_volume goes down; the cut stays.
3. "audio nahi aa raha" → unmute, voice 1.0, music ≤ 0.3 under it.

## Common mistakes to avoid
- Reading "dheere" (softer) as a slower pace.
- Pure digital silence (Chrome stops playing) — the renderer adds a -94 dBFS floor; never remove it.
- True peaks above -1 dBFS (the final limiter keeps it at -1.4).
