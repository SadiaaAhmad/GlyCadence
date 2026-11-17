# GlyCadence Google Cloud ADK Wrapper (`adk web`)

This standalone directory wraps GlyCadence's deterministic diabetes safety, meal, exercise, and wellbeing tools using `google-adk` for Vertex AI / Cloud for Education verification, leaving the core FastAPI + LangGraph + Next.js application completely untouched.

## Setup & Run (`adk web`)
1. Authenticate with Google Cloud:
   ```bash
   gcloud auth application-default login
   ```
2. Install ADK in a dedicated virtualenv:
   ```bash
   cd adk_agent
   pip install -r requirements.txt
   ```
3. Copy `glycadence_adk/.env.example` to `glycadence_adk/.env` and fill in your GCP Project ID and `credentials.json` path (never commit `.env` or `credentials.json`).
4. Launch the ADK web UI:
   ```bash
   adk web
   ```
