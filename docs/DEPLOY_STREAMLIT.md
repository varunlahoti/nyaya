# Deploy to Streamlit Community Cloud

A free way to host the Nyaya app for a private demo. Runs Python 3.11 on their
side (so the local 3.9.7 limitation doesn't apply). **Protected by a password so
public visitors can't spend your Indian Kanoon / OpenRouter credits.**

> ⚠️ This is a demo/testing host, not production. For real users, deploy the
> Next.js + FastAPI stack with proper auth and per-user billing.

---

## What's already wired (no action needed)
- `backend/streamlit_app.py` — reads keys from **Streamlit Secrets**, gates
  access behind a **password**, and runs the pipeline in-process.
- `requirements.txt` (repo root) — the minimal deps Streamlit Cloud installs.
- `.gitignore` — ensures no `.env` or `secrets.toml` with real keys is ever
  committed.

## Your keys are safe
- Real keys live **only** in the Streamlit Cloud dashboard (Secrets) — never in
  the repo.
- `backend/.env`, `.env`, and `.streamlit/secrets.toml` are git-ignored.
- The code reads keys via env/secrets; nothing is hardcoded.

---

## Steps (what you do)

### 1. Put the code on GitHub
```bash
cd /Users/varunlahoti/Judgements
git init
git add .
git status          # CONFIRM: no .env, no backend/.env, no secrets.toml listed
git commit -m "Nyaya legal research app"
# create an empty repo on github.com, then:
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```
> Before pushing, double-check `git status` does **not** list `.env`,
> `backend/.env`, or `.streamlit/secrets.toml`. If it does, stop — the
> `.gitignore` isn't taking effect.

### 2. Create the app on Streamlit Cloud
1. Go to **share.streamlit.io** → sign in with GitHub → **New app**.
2. Repository: your repo · Branch: `main`.
3. **Main file path:** `backend/streamlit_app.py`
4. Deploy.

### 3. Add your secrets (this is where the keys go)
In the app: **⋮ → Settings → Secrets**, paste:
```toml
OPENROUTER_API_KEY = "sk-or-..."
INDIAN_KANOON_API_TOKEN = "your-ik-token"
APP_PASSWORD = "a-strong-password-you-choose"
```
Save. The app restarts and picks them up.

### 4. Use it
Open the app URL → enter your `APP_PASSWORD` → search. Share the URL + password
only with people you trust (every search spends your credits).

---

## Notes
- **Rotate your keys** if they were ever shared in chat/screens before this.
- **Credit control:** the password gate is the guard. Anyone with the password
  can spend credits — treat it like a key.
- **Idle sleep:** free Streamlit apps sleep when unused and wake on next visit
  (first load is slow). Fine for a demo.
- **Local testing** still works via `backend/.env` (no password needed locally,
  since `APP_PASSWORD` isn't set there).
