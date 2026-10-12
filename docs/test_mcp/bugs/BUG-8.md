# BUG-8 — "Could not load projects — Not Found"

- **Seen (user screenshot):** the web app on http://localhost:8081 showed "Not Found"; opening the backend address
  showed `{"error":{"code":"not_found","message":"Not Found"}}`.
- **Root cause:** another project (pre6) listens on port 8000, the app's default backend address. CutMind runs on 8010.
- **Fix:** web client — a 404 on `/projects` says "The server at … is not CutMind … Open Settings …"; API `GET /`
  says what it is and where the app is.
- **Check [RAN]:** in the browser pane: the new message on 8000; Settings → 8010 → projects listed. `curl /` on 8010.
