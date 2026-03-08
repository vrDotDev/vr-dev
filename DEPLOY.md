# Deploy Guide — vr.dev v1.0.0

## Prerequisites

- Python 3.10+
- Docker & Docker Compose (for local/staging)
- Railway CLI (`npm i -g @railway/cli`) — for production API
- PyPI account with `twine` configured — for SDK publish
- Hatch installed (`pip install hatch`)

---

## 1. PyPI — Publish the SDK

```bash
cd packages/vrdev

# Build
hatch build
# Creates dist/vrdev-1.0.0-py3-none-any.whl and .tar.gz

# Verify package contents
tar tzf dist/vrdev-1.0.0.tar.gz | head -20

# Upload (uses ~/.pypirc or TWINE_USERNAME/TWINE_PASSWORD env vars)
twine upload dist/*
```

Verify: https://pypi.org/project/vrdev/1.0.0/

```bash
pip install vrdev==1.0.0
python -c "import vrdev; print(vrdev.__version__)"
# Should print: 1.0.0
```

---

## 2. Railway — Deploy the API

The project is configured via `railway.toml` at the repo root.

```bash
# Login
railway login

# Link to your project (first time only)
railway link

# Deploy
railway up
```

Railway will:
1. Build the Docker image from `packages/vr-api/Dockerfile`
2. Health-check on `/health`
3. Auto-restart on failure (max 3 retries)

### Environment Variables (set in Railway dashboard)

| Variable | Description | Required |
|----------|-------------|----------|
| `VR_DATABASE_URL` | PostgreSQL connection string (NeonDB) | Yes |
| `VR_REDIS_URL` | Redis connection string (add Redis plugin) | Yes |
| `VR_ADMIN_KEY` | Secret for `/v1/quota/*` admin endpoints | Yes |
| `VR_SIGNING_KEY` | Ed25519 PEM private key (escape `\n`) | Yes |
| `OPENAI_API_KEY` | For SOFT-tier LLM verifiers | If using SOFT tier |
| `VR_ANCHOR_PRIVATE_KEY` | Ethereum private key for on-chain anchoring | If anchoring |
| `VR_ANCHOR_CONTRACT` | EvidenceAnchor contract address on Base | If anchoring |
| `VR_BASE_RPC_URL` | Base RPC endpoint (default: `https://sepolia.base.org`) | If anchoring |
| `VR_X402_ENABLED` | Enable x402 USDC payment gating (`1` or `0`) | No (default `0`) |
| `VR_X402_WALLET_ADDRESS` | USDC recipient wallet on Base | If x402 enabled |
| `VR_X402_NETWORK` | `base-sepolia` or `base` | If x402 enabled |
| `VR_CDP_API_KEY` | Coinbase CDP API key ID | If x402 enabled |
| `VR_CDP_API_SECRET` | Coinbase CDP API secret | If x402 enabled |
| `PORT` | Auto-set by Railway | No |

### Verify Deployment

```bash
curl https://YOUR-APP.up.railway.app/health
# {"status":"ok","version":"1.0.0"}
```

---

## 3. Local / Staging — Docker Compose

```bash
# From repo root (vr-dev/)
cp packages/vr-api/.env.example packages/vr-api/.env
# Edit .env with real values

docker compose up -d
```

Services:
- **api**: `http://localhost:8000` — FastAPI application
- **cleanup-worker**: Background evidence TTL cleanup (every 6h)
- **postgres**: `localhost:5432` — PostgreSQL 16
- **redis**: `localhost:6379` — Redis 7

Health check:
```bash
curl http://localhost:8000/health
```

Tear down:
```bash
docker compose down        # stop containers
docker compose down -v     # stop + delete volumes (destructive)
```

---

## 4. Frontend — Vercel (or similar)

The Next.js frontend at `vrdev/` deploys to any Node.js hosting platform.

```bash
cd vrdev
npx next build   # verify build passes locally first
```

For Vercel:
```bash
vercel --prod
```

Or connect the GitHub repo to Vercel and set the root directory to `vrdev/`.

---

## 5. Pre-Launch Checklist

```bash
# Run smoke test
cd vr-dev && python scripts/smoke_test.py

# Run full test suite
cd packages/vrdev && python -m pytest tests/ -v
cd packages/vr-api && python -m pytest tests/ -v

# Validate registry
python scripts/validate_registry.py

# Build frontend
cd ../../vrdev && npx next build
```

All must pass before deploying.

---

## 6. Post-Deploy Verification

1. `pip install vrdev==1.0.0` in a fresh virtualenv
2. `vr verify --verifier filesystem.file_created --ground-truth '{"path": "/tmp/test.txt"}'`
3. `curl https://YOUR-API/health` returns `{"status":"ok","version":"1.0.0"}`
4. Visit https://vr.dev — verify registry page shows 30 verifiers
5. Post to Show HN (see `vr-dev-plan/LAUNCH-POSTS.md`)
