# Enabling real satellite data (Google Earth Engine)

SylvaSense reads its observations — Sentinel-2 L2A, Sentinel-1 GRD, GEDI L4A,
Copernicus DEM GLO-30 and ESA WorldCover — through Google Earth Engine.

Without an Earth Engine credential the backend reports
`EARTH_ENGINE_NOT_CONFIGURED` and **produces no analytical result**. It does not
substitute numbers. The UI surfaces this state explicitly.

## What you need

1. A Google Cloud project.
2. The Earth Engine API enabled on it.
3. A service account **registered with Earth Engine**.
4. A JSON key for that service account.

## The four commands

```bash
# 0. pick your project
export PROJECT_ID=my-forest-project
gcloud config set project "$PROJECT_ID"

# 1. enable the Earth Engine API
gcloud services enable earthengine.googleapis.com

# 2. create a service account
gcloud iam service-accounts create sylvasense-ee \
  --display-name="SylvaSense Earth Engine"

# 3. download a key
gcloud iam service-accounts keys create ./sylvasense-ee-key.json \
  --iam-account="sylvasense-ee@${PROJECT_ID}.iam.gserviceaccount.com"
```

Then **register the service account for Earth Engine** (one-time, in a browser):

<https://code.earthengine.google.com/register> → *Register a service account* →
paste `sylvasense-ee@${PROJECT_ID}.iam.gserviceaccount.com`.

## Point SylvaSense at it

```bash
export SYLVASENSE_PROVIDER=earthengine
export SYLVASENSE_EE_SERVICE_ACCOUNT_FILE=/abs/path/sylvasense-ee-key.json
export SYLVASENSE_EE_PROJECT=$PROJECT_ID
```

or put the same keys in `backend/.env` (already git-ignored).

Container deployments can pass the key inline instead of by path:

```bash
export SYLVASENSE_EE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

## Verify

```bash
curl -s localhost:8000/api/v1/system/status | python3 -m json.tool
```

A working credential reports:

```json
{ "provider": { "active": "earthengine", "mode": "LIVE_EARTH_ENGINE", "ready": true } }
```

If it reports `ready: false`, the `reason` field names the exact failure
(missing key, service account not registered, API not enabled, quota).

## Network requirements

The backend talks to `earthengine.googleapis.com` and, for tiles,
`earthengine-highvolume.googleapis.com`. Both must be reachable. Map tiles are
served to the browser **through the SylvaSense backend**, so the browser itself
needs no Google access and no API key is exposed to the client.

## Note on GEDI

GEDI L4A footprints are sparse: roughly 25 m footprints along ~600 m-spaced
tracks, and the mission does not observe above ~51.6° latitude. SylvaSense
calibrates its biomass model on the GEDI shots that actually fall inside your
AOI. When fewer than `SYLVASENSE_MIN_GEDI_SAMPLES` (default 40) are available it
does **not** invent a local calibration — it falls back to the published
regional model and labels every affected result accordingly.
