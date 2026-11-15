# GlyCadence Demo Day Runbook (Web & Phone)

## 0. Prerequisites (Supply Yourself)
- `.env` in `backend/` with `DATABASE_URL`, `JWT_SECRET_KEY`, and `GEMINI_API_KEY` (never commit `.env`).
- Postgres running locally (`localhost:5432`) with migrations applied (`cd backend; .\.venv\Scripts\alembic.exe upgrade head`).
- `SYNTH-DEMO-001` seeded (`cd backend; .\.venv\Scripts\python.exe scripts\demo_day4.py`).
- Optional primary research cohort: ShanghaiT2DM v3 ingested the night before (`cd backend; .\.venv\Scripts\python.exe -m app.ingestion.run --dataset shanghai_t2dm --archive <path>`), and demo user promoted to researcher via SQL (`UPDATE users SET role='researcher' WHERE email='<demo-email>';`).

---

## 1. Start Backend (Accessible to Both Web & Phone)
Bind FastAPI to `0.0.0.0` so your USB/Wi-Fi phone can reach `http://10.1.161.120:8010`:
```powershell
cd backend
.\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8010
```
Verify health:
```powershell
curl http://127.0.0.1:8010/health
```
Expected: `{"status":"ok","database":"connected"}`.

---

## 2. Start Next.js Web App
```powershell
cd frontend
npm run build
npm run start -- -p 3000
```
Open `http://localhost:3000`:
- `/` — Overview & 4-layer architecture quick link
- `/dashboard` — Sign in, pick `SYNTH-DEMO-001` or ShanghaiT2DM v3 subject, view TIR/TBR/TAR/CV & provenance, run normal investigation + Bad Draft Demo
- `/investigations/[runId]` — Show Agent Trace Timeline, Cross-Signal Findings, Verifier Gate, `execution_mode`/`model_used` banner, and Suggested Patient Questions
- `/architecture` — 4-layer multi-agent architecture slide

---

## 3. Run Flutter App on Your Phone
1. **Allow port 8010 through Windows Defender Firewall** (one-time, Administrator PowerShell):
   ```powershell
   New-NetFirewallRule -DisplayName "GlyCadence FastAPI 8010" -Direction Inbound -LocalPort 8010 -Protocol TCP -Action Allow
   ```
2. Connect your Android phone via USB (with **USB Debugging** enabled) on the **same Wi-Fi** as your PC (`10.1.161.120`).
3. Verify device & launch:
   ```powershell
   cd mobile
   flutter devices
   flutter run -d <device-id>
   ```
4. In the app, tap the Settings gear if your PC LAN IP changed (`http://10.1.161.120:8010` is the default, allowed via scoped `network_security_config.xml`), sign in, pick a patient, view TIR/TBR/TAR/CV + `fl_chart`, and tap **Run Multi-Agent Investigation**.

---

## 4. Failure Fallbacks
- **Gemini quota / network failure:** Pipeline automatically falls back to `deterministic_fallback`, displays the `"Deterministic Template Fallback (Not AI-Generated)"` banner, and still passes the Verifier Gate.
- **Phone cannot reach `10.1.161.120:8010`:** Re-check `ipconfig` for current IPv4, update in mobile Settings screen, or use `adb reverse tcp:8010 tcp:8010` and set mobile API URL to `http://127.0.0.1:8010`.
- **Postgres connection error:** Verify Postgres service is running and `DATABASE_URL` in `backend/.env` matches.
