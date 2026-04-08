# Deploying DARKWATER

## Architecture
Vercel (static frontend `dashboard/frontend/`) + Railway (FastAPI backend + PostgreSQL + Qdrant vector store)

## Prerequisites
- Railway account (railway.app) and CLI: `npm install -g @railway/cli`
- Vercel account (vercel.com) and CLI: `npm install -g vercel`
- Forked copy of this repository

## Step 1 — Backend on Railway
1. `railway login && railway init` (select repo)
2. Add Postgres 16 service and Qdrant service (`qdrant/qdrant:v1.11.3`) from Railway dashboard
3. Deploy backend from repo root (Railway auto-detects `railway.json`)
4. Set env vars from `.env.production.example`:
   - `DEMO_MODE=true`, `API_SECRET_KEY=<random>`
   - `DATABASE_URL` — auto-injected by Railway Postgres service
   - `QDRANT_URL` — set to Railway internal URL of Qdrant service
   - Optional: `COPERNICUS_*`, `GLOBAL_FISHING_WATCH_API_KEY`, `R2_*` for live ingestion
5. Copy your Railway backend URL (e.g. `https://darkwater-backend-xxx.railway.app`)

## Step 2 — Seed Demo Data
```bash
railway run psql $DATABASE_URL -f dashboard/backend/seed_demo_data.sql
```

## Step 3 — Frontend on Vercel
1. `cd dashboard/frontend && vercel`
2. In Vercel dashboard → Settings → Environment Variables, add: `API_BASE=<your Railway URL>`
3. `vercel --prod`

## Step 4 — CI/CD (Optional)
Add GitHub secrets for auto-deploy on push to `main`:
- `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (from Vercel dashboard)
- `RAILWAY_API_TOKEN` (from Railway → Account Settings)

## Verification Checklist
- [ ] Frontend loads at Vercel URL, map shows vessel markers
- [ ] Stats bar shows detection counts
- [ ] Dark vessel filter toggles markers
- [ ] Export CSV downloads valid file
- [ ] Browser DevTools: `/ws/live` WebSocket connected
- [ ] `GET /api/demo-info` returns `{"demo_mode": true}`
- [ ] `POST /api/ingest` returns `403 Forbidden`

## Enabling Live Ingestion
Set `DEMO_MODE=false` and add in Railway:
- `COPERNICUS_CLIENT_ID` + `COPERNICUS_CLIENT_SECRET` (dataspace.copernicus.eu)
- `GLOBAL_FISHING_WATCH_API_KEY` (globalfishingwatch.org)
- `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (Cloudflare R2)

## Troubleshooting
| Symptom | Fix |
|---------|-----|
| No markers on map | Check `API_BASE` in Vercel env vars |
| WebSocket fails | Ensure Railway allows WSS; check CORS_ORIGINS includes Vercel URL |
| DB connection error | Verify `DATABASE_URL` is set; check Postgres service is healthy |
| 403 on write endpoints | Expected with `DEMO_MODE=true` |
