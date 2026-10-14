# Data Sufficiency Arena — Live Leaderboard Edition

A 30-question, 15-minute Streamlit quiz with a live classroom leaderboard.

## What is new
- Student/pair names and classroom room codes
- Shared leaderboard that refreshes every 5 seconds
- Ranking by score (highest first), then faster completion time
- Teacher control view
- CSV export of the leaderboard
- Auto-submit when 15 minutes expire
- Supabase cloud database support for students on separate devices
- Local SQLite fallback for testing on one running server

## Important: how live sharing works
For 70 students on different phones/laptops, deploy the app online and configure Supabase. The local SQLite fallback does **not** share a leaderboard across separate computers or separate cloud instances.

## Step 1 — Make a free Supabase project
1. Go to https://supabase.com/ and create/sign in to an account.
2. Create a new project. Keep the project region close to your class if possible.
3. Open **SQL Editor** in Supabase.
4. Open `supabase_setup.sql` from this folder, copy its contents into the SQL Editor, and run it.
5. In **Project Settings → API** (or the API keys page), copy the Project URL and the publishable/anon key. Never put a service-role key in this app.

## Step 2 — Configure the app secrets
For local testing, create a folder named `.streamlit` beside `app.py`, then create `.streamlit/secrets.toml` containing:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_ANON_KEY = "YOUR-PUBLISHABLE-OR-ANON-KEY"
DSA_ROOM_CODE = "BBA30"
```

Use the publishable/anon key only. Do not use the service-role key.

Then install and run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Step 3 — Publish so students can join
1. Push the project folder to a GitHub repository.
2. Go to https://share.streamlit.io/ and deploy the repository.
3. In the Streamlit app's **Settings / Secrets**, add the same three settings in TOML format.
4. Share the deployed URL and the room code (default: `BBASCMS`) with students.
5. Open the same URL in another tab/device and select **Live leaderboard**. It refreshes every 5 seconds.

## How to play in class
- Students individually or in pairs open the shared app URL.
- Everyone uses the same room code but a distinct player/pair name.
- Each attempt has a 15-minute timer beginning when that student clicks Join & Start.
- Scores appear on the leaderboard after submission or automatic timeout.
- Ties are broken by completion time.
- The teacher can leave the leaderboard view projected.

## Files
- `app.py` — application
- `questions.json` — 30-question bank and explanations
- `requirements.txt` — dependencies
- `supabase_setup.sql` — SQL to create the shared results table
- `README.md` — setup instructions

## Classroom security note
This is designed as a simple classroom game, not a secure exam proctoring system. The example database policies permit anonymous classroom submissions and reads. Anyone with the app URL and room code could submit a score, so use it for practice/engagement rather than high-stakes assessment. If you need stronger control, add authenticated student accounts and restrict database permissions.
