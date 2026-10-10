"""Writes eval/intent_corpus.yaml: realistic noob phrasings for the 40 most-used skills + restore / white requests.

Written by hand on 2026-10-10 BEFORE any tuning on it, in the style of real chat messages (typos, Hinglish
spellings, Devanagari, slang, filler words, run-on voice-style sentences, "yaha" with a marker). Not copied from
the skill YAML synonyms or examples. Every 4th phrase of each skill goes to the HELD-OUT split, which is never
looked at while tuning (docs/INTENT_EVAL.md reports it once).

    backend/.venv/Scripts/python.exe eval/intent_corpus_src.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

MONO = {"marker_time": 4.3, "effects_present_at_time": [{"type": "grade", "label": "black and white", "start": 3.0, "end": 5.5}]}
ZOOM = {"marker_time": 2.0, "effects_present_at_time": [{"type": "zoom", "label": "zoom", "start": 1.0, "end": 3.0}]}
MARK = {"marker_time": 3.0}

S: dict[str, list] = {
    "trim": ["bas 2 se 8 sec tak rakho baaki hata do", "video ko 0 se 10 second tak hi rakhna", "starting ke 3 sec aur end ke baad ka kaat do 3 se 12 rakho",
             "sirf 5 se 15 sec wala part chahiye", "trim kr do 1 se 6 sec", "bhai 4 sec se 9 sec tak ka hi rakh", "keep only 2 to 7 seconds",
             "cut it down to 3-10 sec", "4 सेकंड से 10 सेकंड तक रखो", "trimm 0 to 5 sec"],
    "delete_segment": ["3 se 5 sec wala hissa hata do", "2 se 4 second ka part delete karo", "beech ka 6 se 8 sec nikal do", "remove 1 to 3 sec",
                       "7 se 9 sec bekar hai uda do", "ye 2-3 sec wala part hatao", "delete from 5 to 6 seconds", "4 से 6 सेकंड हटा दो",
                       "10 se 12 sec kaat ke hata do yaar", "dlt 3 to 4 sec"],
    "remove_silence": ["jaha koi bol nahi raha wo hata do", "chup wale part nikal do", "silence hata do please", "khamoshi wale hisse kaat do",
                       "remove the silent parts", "jab main ruk raha hu wo gap hata do", "dead air remove karo", "चुप वाले हिस्से हटाओ",
                       "silnce hatao", "pause wale part uda do sab"],
    "fit_to_duration": ["30 sec ka bana do", "video 15 second ki kar do", "isko 1 minute me fit karo", "make it 20 seconds long",
                        "pura video 45 sec me la do", "reel ke liye 30 sec ka chahiye", "60 सेकंड का बना दो", "10 sec ka chota version",
                        "ise 25 sec ka krdo", "total length 40 sec rakho"],
    "speed_up": ["video fast kar do", "thoda tez chalao", "2x speed kar do", "speed badha do", "make it faster", "1.5x pe chalao",
                 "isko jaldi jaldi chalao", "तेज़ कर दो", "fst kr do video", "speeed up karo bhai"],
    "slow_motion": ["slow motion kar do", "dheere dheere chalao", "slowmo laga do", "half speed kar do", "make it slow",
                    "yaha slow mo dalo", "dheema kar do video", "स्लो मोशन करो", "slo mo plz", "0.5x pe chalao"],
    "zoom_in": ["zoom karo", "thoda zoom in karo", "andar ki taraf zoom", "zoom in kar do 2 se 4 sec", "close up jaisa zoom",
                "zoom krdo yaha", "slow zoom in", "ज़ूम करो", "zom in karo", "face pe zoom in karo"],
    "zoom_out": ["zoom out karo", "bahar ki taraf zoom", "pichhe ki taraf zoom karo", "zoom out kar do end me", "wide karo zoom out se",
                 "dheere se zoom out", "ज़ूम आउट करो", "zoom aout", "reverse zoom karo", "camera pichhe jaye aisa zoom"],
    "shake": ["shake karo", "video hilao", "camera shake daalo", "jhatka do video ko", "earthquake jaisa hilao", "hilne wala effect",
              "shake effect lagao drop pe", "हिलाओ वीडियो", "shak karo", "thoda kaanpta hua karo"],
    "crossfade": ["clips ke beech crossfade", "smooth transition do clips me", "ek clip se dusre me dheere badlo", "dissolve lagao",
                  "crossfade krdo sab cuts pe", "blend karke badlo shots", "क्रॉसफेड लगाओ", "crosfade", "fade karke jodo clips", "mix transition do"],
    "fade_black": ["end me black me fade karo", "kaale me fade out", "shuru me black se fade in", "fade to black", "andhera hote hue khatam",
                   "black screen me dheere jao", "अंत में काला फेड", "fade blak", "fade in fade out kaala", "dhire dhire kala ho jaye end me"],
    "fade_white": ["white me fade karo transition", "safed fade between clips", "fade through white karo", "white transition do",
                   "ujale wala transition", "dream jaisa white fade", "सफ़ेद फेड करो", "wite fade", "clips ke beech white fade", "fade to white karo"],
    "flash": ["flash lagao", "camera flash jaisa", "white flash do cut pe", "chamak do beat pe", "ek flash de do yaha", "photo click wala flash",
              "flash effect", "चमक दो", "flsh karo", "beat pe safed flash"],
    "grayscale": ["black and white kar do", "b&w karo", "rang hata do", "purani film jaisa black white", "grey kar do video",
                  "colour nikal do", "black n white", "ब्लैक एंड व्हाइट करो", "blak and wite", "bina rang ka kar do"],
    "sepia": ["sepia kar do", "purana bhura look", "old photo jaisa brown", "sepia tone lagao", "vintage brown colour", "bhura sa purana",
              "सीपिया करो", "sepiya", "old brown filter", "dada ji ki photo jaisa"],
    "brightness": ["thoda bright karo", "roshni badhao", "video dark hai bright karo", "brightness badha do", "andhera hai ujala karo",
                   "make it brighter", "ब्राइट करो", "brite karo", "zyada roshni chahiye", "brightness kam karo thoda"],
    "contrast": ["contrast badhao", "thoda contrast", "zyada punchy contrast", "contrast kam karo", "colors ko gehra karo contrast se",
                 "increase contrast", "कंट्रास्ट बढ़ाओ", "contrst", "dark aur light ka farak badhao", "contrast high karo"],
    "saturation": ["colors zyada karo", "rang badha do", "saturation badhao", "vibrant bana do", "colour pop karo zyada", "rang halka karo",
                   "रंग बढ़ाओ", "satration up", "colours bright aur gehre", "saturation kam karo"],
    "warm": ["warm kar do", "garam tone do", "golden look", "sunset jaisa peela", "thoda warm", "garmi wala colour", "गर्म रंग करो",
             "warmm", "orange tint do", "dhoop jaisa colour"],
    "cool": ["cool tone do", "thanda colour", "blue tint karo", "neela sa look", "thoda cool", "sardi wala colour", "ठंडा रंग",
             "kool tone", "icy look do", "blueish kar do"],
    "cinematic_look": ["cinematic bana do", "movie jaisa look", "film wala colour", "cinematic grade karo", "hollywood look do",
                       "picture jaisa feel", "सिनेमैटिक करो", "cinamatic", "filmy look do", "movie colour grading"],
    "vintage_faded": ["vintage look do", "faded purana look", "retro faded colour", "old faded film", "90s faded look", "halka purana rang",
                      "विंटेज करो", "vintag", "faded karo colours", "retro wala halka look"],
    "auto_captions": ["subtitles daal do", "captions lagao", "jo bol raha hu wo likh do", "text me bolna dikhao", "auto captions",
                      "sub title chahiye", "कैप्शन लगाओ", "captons", "har baat ka text niche", "subs add karo"],
    "text_overlay": ["upar 'Goa' likh do", "text daalo 'Happy'", "screen pe 'WOW' likho", "naam likh do 'Rahul'", "'Sale' text add karo",
                     "beech me 'Hello' likhna", "'शुभ दिन' लिखो", "txt 'Party' daalo", "likh do 'Best day'", "'Nice' word dikhao"],
    "title_card": ["shuru me title card 'Trip'", "title daalo 'My Vlog'", "opening title 'Diwali'", "heading card 'Goa 2026'",
                   "starting me naam ka card", "title screen 'Episode 1'", "शीर्षक कार्ड 'यात्रा'", "titel card 'Fun'",
                   "intro title 'Shaadi'", "bada title 'Hello' start pe"],
    "caption_style": ["captions yellow karo", "subtitle ka style hormozi", "captions bade karo", "text ka color white karo",
                      "caption style neon", "subtitles bold karo", "कैप्शन पीले करो", "captn style badlo", "caption font mota karo", "captions minimal style"],
    "add_music": ["music lagao", "gaana daalo", "background music chahiye", "koi song laga do", "upbeat music add karo", "bgm daal do",
                  "गाना लगाओ", "musik lagao", "piche halka music", "song add kar do"],
    "volume": ["awaaz badhao", "volume kam karo", "sound tez karo", "awaz dheemi karo", "louder karo", "volume up", "आवाज़ बढ़ाओ",
               "volum kam", "music ki awaaz kam karo", "awaaz thodi zyada"],
    "mute": ["awaaz band karo", "mute kar do", "sound hata do", "bina awaaz ka", "silent kar do video", "no sound", "आवाज़ बंद करो",
             "mut karo", "audio off karo", "chup kara do video ko"],
    "denoise": ["background noise hatao", "shor kam karo", "awaaz saaf karo", "noise remove", "hiss hata do", "hawa ki awaaz hatao",
                "शोर हटाओ", "nois hatao", "peeche ka shor kam", "clean audio karo"],
    "duck_music": ["jab bolu tab music dheema", "voice ke time gaana kam", "duck music", "baat ke beech music neeche", "music ko voice ke liye dabao",
                   "bolte waqt background kam", "बोलते समय संगीत कम", "duk music", "voice pe music halka", "talking pe music down"],
    "audio_fade": ["awaaz dheere se shuru ho", "sound fade out end me", "music fade in karo", "audio fade in aur out", "gaana dheere khatam ho",
                   "volume fade karo", "आवाज़ धीरे से खत्म", "audio fad out", "end me music dheere band", "sound smoothly start ho"],
    "aspect_9_16": ["reel ke liye vertical karo", "9:16 bana do", "instagram reel size", "shorts ke liye khada video", "vertical format",
                    "phone wala lamba size", "वर्टिकल करो", "9 by 16", "tiktok size karo", "portrait mode me karo"],
    "aspect_1_1": ["square bana do", "1:1 karo", "instagram post size square", "chokor video", "square format", "1 by 1 ratio",
                   "स्क्वेयर करो", "sqare", "post ke liye square", "barabar lambai chaudai"],
    "blur": ["blur karo", "dhundla kar do", "video dhundhli karo", "blur effect", "halka blur", "dreamy blur", "धुंधला करो", "blurr",
             "saaf mat dikhao blur karo", "focus hata ke blur"],
    "glitch": ["glitch effect", "glitch lagao", "toota hua digital effect", "glitchy karo", "signal kharab wala effect", "glich karo",
               "ग्लिच करो", "glitchh", "error wala effect", "digital gadbad dikhao"],
    "vhs_retro": ["vhs look", "purani cassette jaisa", "vhs effect do", "retro tape wala", "80s vhs", "video cassette look", "वीएचएस लुक",
                  "vhs retro", "old tv tape jaisa", "vcr wala look"],
    "watermark_logo": ["logo lagao corner me", "watermark daalo", "apna logo add karo", "brand logo kone me", "logo chipka do",
                       "watermark lagao", "लोगो लगाओ", "watermrk", "channel logo dikhao", "logo daal do niche"],
    "export_preset": ["instagram ke liye export", "youtube shorts ke liye nikalo", "whatsapp status ke liye", "reels export karo",
                      "youtube ke liye ready karo", "linkedin ke liye export", "यूट्यूब के लिए", "exprt for insta", "status ke liye video",
                      "shorts ke liye final"],
    "restore_normal": [("yaha normal kar do", MONO), ("pehle jaisa kar do yaha", MONO), ("ye effect hata do yahan", MONO),
                       ("yaha original jaisa tha waisa karo", MONO), ("ye black white hatao yaha se", MONO), ("yahan wapas normal", MONO),
                       ("yaha zoom hata ke normal karo", ZOOM), ("is jagah pehle wala look", MONO), ("यहाँ पहले जैसा करो", MONO),
                       ("yhn nrml krdo", MONO), ("effect nikal do idhar se jaisa tha", ZOOM), ("ye wala change undo karo yaha", MONO)],
    "brighten_to_white": [("yaha screen white sa kar do", MARK), ("thoda safed sa karo yahan", MARK), ("yaha picture ko white wash karo", MARK),
                          ("is jagah overexpose karo", MARK), ("yaha dhula dhula safed", MARK), ("screen ko bright white sa", MARK),
                          ("यहाँ सफ़ेद सा करो", MARK), ("yaha whitish kar do", MARK)],
    "white_screen_card": [("yaha 1 sec white screen daalo", MARK), ("beech me safed screen dikhao", MARK), ("yaha khali white screen", MARK),
                          ("is jagah white card lagao", MARK), ("yahan blank white screen 2 sec", MARK), ("सफ़ेद स्क्रीन यहाँ", MARK),
                          ("yaha wite screen", MARK), ("ek safed parda dikha do yaha", MARK)],
}
# the original failure, both readings (with / without an effect on screen)
BUG = [{"prompt": "yaha screen white kar do nomal jasia tha", "context": MONO, "expect": "restore_normal", "also_top3": ["flash"]},
       {"prompt": "yaha screen white kar do nomal jasia tha", "context": {"marker_time": 4.3}, "expect": "flash"}]


def main() -> None:
    items = list(BUG)
    for sid, phrases in S.items():
        for i, x in enumerate(phrases):
            prompt, ctx = (x if isinstance(x, tuple) else (x, None))
            item = {"prompt": prompt, "expect": sid, "split": "heldout" if i % 4 == 3 else "dev"}
            if ctx:
                item["context"] = ctx
            items.append(item)
    out = Path(__file__).with_name("intent_corpus.yaml")
    out.write_text(yaml.safe_dump({"written": "2026-10-10", "items": items}, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    print(len(items), "items,", sum(1 for x in items if x.get("split") == "heldout"), "held-out")


if __name__ == "__main__":
    main()
