# Deploying Parcel Scout to Fly.io

This is the step-by-step runbook for moving the app off Streamlit Cloud and onto Fly.io's persistent infrastructure. After this, the SQLite database survives restarts and deploys.

## What you'll have when you're done

- `https://giovanni-bonelli-parcel-scout.fly.dev` — reachable from any browser
- Password-protected sign-in page — only people with the password get in
- SQLite database on a 1GB persistent volume that survives restarts
- Automatic daily volume snapshots (free tier keeps 5 days)
- Auto-stop when idle → ~$0.15/month in total

## Prerequisites (one-time, on your Mac)

```bash
# Install the Fly CLI
brew install flyctl

# Sign in (creates account if you don't have one)
flyctl auth signup
# (or: flyctl auth login  if you already have an account)

# Confirm you're logged in
flyctl auth whoami
```

## 1. Launch the app (no deploy yet)

```bash
cd "/Users/davidgellebrecht/Dropbox (Personal)/Claude Code/Parcel Scout"

# Create the Fly app using the existing fly.toml as-is.
# --no-deploy stops Fly from trying to deploy before we've set secrets.
flyctl launch --copy-config --name giovanni-bonelli-parcel-scout --region cdg --no-deploy
```

When Fly asks *"Would you like to copy its configuration to the new app?"* answer **yes**. When it asks about databases/Redis, answer **no**.

## 2. Create the persistent volume

```bash
flyctl volumes create parcel_scout_data --region cdg --size 1 --yes
```

This creates the 1GB disk that holds `data/parcel_scout.sqlite`. The name `parcel_scout_data` must match `source` in `fly.toml` — don't change it.

## 3. Set secrets

Secrets are Fly's version of the API keys in Streamlit Cloud's secrets tab. Unlike `st.secrets`, these live as environment variables inside the VM and never appear in logs or the repo.

Replace the `...` values below with your real keys before pasting. The password you pick is how you (and whoever you share it with) will sign in.

```bash
flyctl secrets set \
  PARCEL_SCOUT_ACCESS_PASSWORD='pick-a-strong-team-password' \
  OPENAPI_IT_KEY='...' \
  SENTINEL_HUB_CLIENT_ID='...' \
  SENTINEL_HUB_CLIENT_SECRET='...' \
  TRIPADVISOR_API_KEY='...' \
  WINE_SEARCHER_API_KEY='...'
```

You can copy the existing values straight from your Streamlit Cloud "Secrets" tab. If a key is blank in Streamlit Cloud, leave it out of this command entirely.

Share `PARCEL_SCOUT_ACCESS_PASSWORD` with teammates through a password manager (1Password / Bitwarden / Apple Passwords), not through email or chat.

## 4. Deploy

```bash
flyctl deploy
```

First build takes ~3–4 minutes. Fly builds the Docker image, pushes it to its registry, creates a VM, mounts the volume, and starts the app. When it finishes you'll see:

```
Finished deploying
```

Test it:

```bash
# Open the app
open https://giovanni-bonelli-parcel-scout.fly.dev
```

You should see the password gate. Enter `PARCEL_SCOUT_ACCESS_PASSWORD` → the app appears.

## 5. (Optional) Import your existing data

If you have historical `ranked_*.json` files on your Mac that you want on the Fly volume, use the **"Import historical runs into DB"** button inside the app — it's in the API-usage expander under the cost badge. One click, pulls every file into the Fly-hosted DB.

## 6. Keep Streamlit Cloud live during the cutover

Nothing in this guide touches your Streamlit Cloud deployment. You can:

1. Deploy to Fly
2. Confirm it works
3. Share the Fly URL with your team
4. Turn off the Streamlit Cloud deployment whenever you're comfortable (just delete the app from share.streamlit.io)

Zero-risk: both can run in parallel for as long as you want.

## Ongoing operations

```bash
# Tail logs when something looks off
flyctl logs

# Deploy a new version after you push code changes to GitHub
# (Note: Fly deploys from your local working dir, NOT from GitHub — so
#  `flyctl deploy` pushes what you have locally, committed or not.)
flyctl deploy

# Restart the VM to pick up new secrets
flyctl machines restart

# Check status
flyctl status

# Change a secret
flyctl secrets set PARCEL_SCOUT_ACCESS_PASSWORD='new-password'

# List current secrets (values masked)
flyctl secrets list

# SSH into the running VM (useful for debugging the volume contents)
flyctl ssh console
# Inside: ls -la /app/data  → should show parcel_scout.sqlite + WAL files
```

## Cost expectations

- **VM**: $0 while idle (auto-stops after a few minutes of no traffic)
- **Volume**: 1GB × $0.15/GB/mo = **$0.15/mo**
- **Bandwidth**: first 160GB/mo free (you won't come close)
- **Snapshots**: free on the free tier

Realistic monthly cost: **~$0.15** unless the app is running constantly, in which case you'll see a small VM bill ($2-5/mo for shared-cpu-1x).

## Troubleshooting

**"App failed to start"** — `flyctl logs` and look for Python tracebacks. Most common: a missing dependency in `requirements.txt`. Add it, `flyctl deploy` again.

**"Password page doesn't appear"** — the env var isn't set. Run `flyctl secrets list` and confirm `PARCEL_SCOUT_ACCESS_PASSWORD` shows up. If it's there but the page still doesn't gate, run `flyctl machines restart`.

**"Scan works but doesn't persist"** — the volume didn't mount. Run `flyctl ssh console` and check `ls -la /app/data`. Should have `parcel_scout.sqlite`. If `/app/data` is empty or missing, the volume wasn't created — go back to step 2.

**"Health check failing"** — Streamlit takes up to 60 seconds to boot on a cold machine. The `grace_period` in `fly.toml` is set to 60s; if you're consistently seeing boot failures, bump it to 120s and redeploy.

## Destroying it

If you want to turn the Fly deployment off entirely:

```bash
flyctl apps destroy giovanni-bonelli-parcel-scout
```

This deletes the app, VM, and volume. Your Mac and GitHub repo are untouched.
