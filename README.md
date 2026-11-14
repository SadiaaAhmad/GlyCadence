# GlyCadence

**Longitudinal Diabetes & Wellbeing Intelligence Companion**

GlyCadence is a full-stack Type 2 diabetes and wellbeing intelligence platform built on a four-layer architecture:
1. **Data Ingestion & Storage** — PostgreSQL (15+) with cohort-isolated longitudinal records.
2. **Deterministic Analytics** — Python (`Pandas`, `NumPy`, `SciPy`, `Scikit-learn`) for baselines, TIR/TBR/TAR, drift, and postprandial meal iAUC.
3. **Agentic Reasoning & Fail-Closed Safety** — LangGraph + Gemini API + mandatory 3-layer deterministic Safety Guard.
4. **Patient & Clinician Outputs** — Next.js App Router web app + ReportLab one-page clinician PDFs.

---

## Project Structure

```text
GlyCadence/
├── frontend/          # Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts
├── backend/           # Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy
├── database/          # Alembic migrations & seed scripts
├── datasets/          # Git-ignored raw & processed research datasets
├── docs/              # Architecture & evaluation reports
├── docker-compose.yml # PostgreSQL 15 + backend + frontend
└── .env.example       # Environment variable template
```

---

## Setup & Environment Configuration

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
2. Update `.env` with your local PostgreSQL credentials (`POSTGRES_PASSWORD`, `DATABASE_URL`) and secrets. Never commit `.env` to Git.

---

## Running Locally

### Option A: Docker Compose (PostgreSQL 15 + Backend + Frontend)
```bash
docker compose up --build
```

### Option B: Run Services Independently

#### 1. PostgreSQL (Minimum Version 15)
Ensure PostgreSQL 15+ is running on `localhost:5432` and the database configured in `DATABASE_URL` exists (or run only the database service via `docker compose up -d postgres`).

#### 2. Backend (FastAPI — Python 3.11+ Standardized; `python:3.11-slim` in Docker)
```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```
- Selected local development port: `8010` (avoids host port `8000` conflicts).
- API Docs: `http://localhost:8010/docs`
- Liveness check: `GET http://localhost:8010/api/v1/health`
- Database check: `GET http://localhost:8010/api/v1/health/db`

#### 3. Frontend (Next.js)
```bash
cd frontend
npm install
npm run dev
```
- Web App: `http://localhost:3000`

---

## Verification Tests (Day 1)
```bash
cd backend
.\.venv\Scripts\pytest.exe
```
