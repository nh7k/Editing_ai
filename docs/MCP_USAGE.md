# CutMind ko Claude Desktop se kaise use karein (simple Hinglish)

## 1. Ek baar ka setup (aap khud karoge — main aapki config file nahi chhoota)

**Backup pehle** (PowerShell me):

```powershell
Copy-Item "$env:APPDATA\Claude\claude_desktop_config.json" "$env:APPDATA\Claude\claude_desktop_config.backup-2026-10-12.json"
```

**Config file:** `C:\Users\itanm\AppData\Roaming\Claude\claude_desktop_config.json`
(ya Claude Desktop → Settings → Developer → Edit Config).

Aapki file me abhi `coworkUserFilesPath` aur `preferences` hain, `mcpServers` nahi. **Diff** — `"preferences": {...}`
ke baad ek comma aur ye block jodo (baaki kuch mat chhedo):

```diff
   "preferences": { … jaisa hai waisa … }
+  ,
+  "mcpServers": {
+    "cutmind": {
+      "command": "C:\\Users\\itanm\\OneDrive\\Desktop\\video editing\\backend\\.venv\\Scripts\\python.exe",
+      "args": ["-m", "cutmind.mcp_server", "--mode", "edit"],
+      "env": {
+        "PYTHONPATH": "C:\\Users\\itanm\\OneDrive\\Desktop\\video editing\\backend",
+        "CUTMIND_URL": "http://localhost:8010"
+      }
+    },
+    "cutmind-test": {
+      "command": "C:\\Users\\itanm\\OneDrive\\Desktop\\video editing\\backend\\.venv\\Scripts\\python.exe",
+      "args": ["-m", "cutmind.mcp_server", "--mode", "test"],
+      "env": {
+        "PYTHONPATH": "C:\\Users\\itanm\\OneDrive\\Desktop\\video editing\\backend",
+        "CUTMIND_TRANSLATOR": "off",
+        "LLM_PROVIDER": "rules"
+      }
+    }
+  }
 }
```

Koi password / key nahi chahiye. JSON me ek bhi extra comma ho to Claude Desktop chupchaap ignore karta hai — save
karne se pehle editor me check karo.

**Phir:**
1. CutMind backend chalu karo (EDIT MODE ke liye; TEST MODE ka apna andar hai).
   Port 8000 pe aapka "pre6" chalta hai, isliye CutMind 8010 pe: `backend\.venv\Scripts\python.exe -m uvicorn cutmind.api:create_app --factory --app-dir backend --host 127.0.0.1 --port 8010`
2. Claude Desktop **poora band karo**: system tray (ghadi ke paas) me Claude icon → Quit. Sirf window band karna kaafi nahi.
3. Claude Desktop kholo → chat box me tools / hammer icon → "cutmind" aur "cutmind-test" dikhne chahiye.
4. **Smoke test** (ek line, Claude ko type karo): `cutmind ka health_check chalao aur batao api_ok kya hai`

Video dene ke liye: file ko `C:\Users\itanm\CutMind\inbox` me rakho (sirf yahi folder allowed hai).

## 2. EDIT MODE — Claude se edit karwao (15 example jumle)

1. "CutMind health check karo aur mere saare projects dikhao."
2. "'ronaldo' project kholo aur batao abhi edit me kya-kya hai."
3. "Naya project 'goa trip' banao aur inbox wali goa.mp4 daal do."
4. "Is video ko gaane ki beat pe edit karo — pehle dry run me batao kya karoge."
5. "4 se 6 second ke beech black and white karo, phir check karke batao sach me hua ya nahi."
6. "Thoda warm karo aur halka vignette lagao."
7. "Jo main bol raha hu wo screen pe aaye, handle @meraname."
8. "Captions laga do aur unka colour peela karo."
9. "End me fade to black karo."
10. "3 variations banao is reel ke, phir doosra wala use karo."
11. "Last change undo karo aur dono versions compare karke batao kya badla."
12. "Video ko measure karke batao: lambai, awaaz ka level, end frame kaala hai ya nahi."
13. "Version 2 wapas le aao."
14. "Auto edit button dabao."
15. "Final video export karo." (Claude confirm maangega)

Claude chhote steps me kaam karta hai: samjho → skill dhoondho → (dry run) → lagao → check karo → batao → undo offer.

## 3. TEST MODE — app ka apna dimaag test karna

`cutmind-test` me Claude **skill khud nahi chun sakta** (wo tools hain hi nahi). Har jumla `run_prompt` se waise hi app
me jata hai jaise aap app me type karte ho. Ye apne alag workspace (`C:\Users\itanm\CutMind\test_workspace`) me chalta
hai — aapke asli projects kabhi nahi chhoote.

Shuru karne ke liye Claude ko bolo:
> "cutmind-test use karo. create_fixture se speech_pauses banao, naya project banao, clip daalo, phir run_prompt se
> exactly ye bhejo: 'silence hata do aur captions lagao'. Prompt ko badalna mat. Phir verify_output aur
> compare_claims_vs_measurements chala ke batao app ne sahi kiya ya nahi."

Bade test (200 cases) Python runner chalata hai (`tools/test200`), Claude Desktop nahi.

## 4. Kuch na dikhe to (troubleshooting)

| dikkat | kya karo |
|---|---|
| tools icon me cutmind nahi | JSON check karo (comma!), Claude Desktop tray se Quit karke kholo |
| "api_ok": false | CutMind backend chalu nahi / ya port galat; CutMind 8010 pe chalao aur `CUTMIND_URL` = http://localhost:8010 |
| "folder is not allowed" | file `C:\Users\itanm\CutMind\inbox` me rakho, ya `CUTMIND_MCP_ALLOW` me folder jodo |
| python / module error | `command` me venv ka python.exe ka poora path ho, `PYTHONPATH` = backend folder |
| Claude Desktop ke logs | `%APPDATA%\Claude\logs\mcp-server-cutmind.log` (Claude Desktop ka) |
| hamare tool logs | `C:\Users\itanm\CutMind\mcp_logs\mcp-YYYYMMDD.jsonl` (`get_logs` tool se bhi) |

## 5. claude.ai (website) se jodna — ek command

claude.ai aapke laptop tak sirf ek public **https** link se pahunch sakta hai. Ye ek command sab chalu karta hai —
CutMind backend (127.0.0.1:8010), MCP server (127.0.0.1:8020, secret link) aur Cloudflare tunnel (sirf MCP bahar
dikhta hai, backend nahi):

```powershell
backend\.venv\Scripts\python.exe tools\start_remote.py
```

Ye link print karta hai (aur app me **Settings → Connect to Claude** me "Copy link" button). Phir:
1. claude.ai → Settings → Connectors → **Add custom connector** → Name `cutmind`, URL = link, sign-in: none → Add
2. Naye chat me tools icon se `cutmind` on → "cutmind ka health_check chalao"

- `cloudflared` ek baar chahiye: `~/CutMind/bin/cloudflared.exe` — Cloudflare ki official GitHub release (2026.9.3,
  SHA256 `f096265e…e7e2`, Windows signature "Cloudflare, Inc." — dono check kiye).
- Link ek **password** hai: jiske paas link, wo aapke projects edit kar sakta hai (login abhi nahi hai).
- Free tunnel ka link har start pe badalta hai. Purana link band karna: `tools\start_remote.py --rotate` (naya token).
- Window band = tunnel band.
- claude.ai me attach ki photo/video laptop tak nahi aati: file `C:\Users\itanm\CutMind\inbox` me rakho aur Claude se
  "inbox wali car1.jpg naye project me daalo" bolo. Photos (JPG/PNG/WEBP) clip ban jaati hain; "in photos se edit
  banao" = beat pe photo montage (camera push-in, cinematic look). Naye scene generate karna (jaise car ko jami jheel
  pe rakhna) is laptop pe free me NAHI ho sakta — GPU wala video-generation model chahiye.
