import json
import os
import time
import uuid
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

try:
    from supabase import create_client
except ImportError:
    create_client = None

st.set_page_config(page_title="Data Sufficiency Quiz", layout="wide", initial_sidebar_state="collapsed")

DATA = json.loads((Path(__file__).parent / "questions.json").read_text(encoding="utf-8"))
QUESTIONS = DATA["questions"]
CHOICES = DATA["choices"]
LETTERS = list(CHOICES.keys())
TOTAL = len(QUESTIONS)
DURATION_SECONDS = 15 * 60
DEFAULT_ROOM = os.getenv("DSA_ROOM_CODE", "BBA_SCMS")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap');
html, body, [class*="css"] { font-family: 'Nunito', sans-serif; }
.stApp { background: linear-gradient(135deg,#07152e 0%,#102a56 48%,#182e49 100%); color:#f8fafc; }
.block-container { max-width: 1300px; padding-top: 1rem; padding-bottom: 3rem; }
h1,h2,h3,p,label,.stMarkdown { color:#f8fafc; }
.hero { padding:1.5rem 1.8rem; border-radius:24px; background:linear-gradient(120deg,#6d28d9,#2563eb 65%,#0891b2); box-shadow:0 12px 40px #0005; margin-bottom:1rem; }
.hero h1 { font-size:clamp(2rem,4vw,3.4rem); line-height:1.05; margin:0; font-weight:900; }
.hero p { font-size:1.1rem; margin:.6rem 0 0; color:#eff6ff; }
.metric { background:#ffffff12; border:1px solid #ffffff25; border-radius:18px; padding:1rem; text-align:center; min-height:96px; }
.metric .value { font-size:2rem; font-weight:900; color:#facc15; }
.metric .label { font-size:.92rem; color:#dbeafe; }
.panel { background:#ffffff10; border:1px solid #ffffff25; padding:1.2rem 1.4rem; border-radius:22px; margin:.7rem 0; }
.q-number { color:#93c5fd; font-size:.95rem; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
.question { font-size:clamp(1.3rem,2.2vw,1.9rem); font-weight:900; line-height:1.35; margin:.6rem 0 1rem; }
.statement { font-size:1.15rem; line-height:1.5; background:#ffffff12; border-left:5px solid #38bdf8; border-radius:10px; padding:.8rem 1rem; margin:.55rem 0; }
div.stButton>button { border-radius:12px; font-size:1rem; font-weight:800; min-height:2.8rem; }
div[role="radiogroup"] label { background:#ffffff0d; border:1px solid #ffffff25; border-radius:12px; padding:.6rem .8rem; margin:.2rem 0; }
div[role="radiogroup"] label p { font-size:1rem !important; }
.stProgress>div>div>div>div { background:linear-gradient(90deg,#a78bfa,#38bdf8); }
.small-note { color:#cbd5e1; font-size:.92rem; }
.lb-row { padding:.7rem 1rem; border-radius:12px; background:#ffffff0e; border:1px solid #ffffff1a; margin:.3rem 0; }
</style>
""", unsafe_allow_html=True)

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def db_path():
    return Path(__file__).parent / "leaderboard.sqlite"

def local_db():
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id TEXT PRIMARY KEY, room TEXT, player TEXT, score INTEGER, total INTEGER,
        attempted INTEGER, elapsed_seconds INTEGER, submitted_at TEXT, answers_json TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_room ON submissions(room)")
    conn.commit()
    return conn

def get_supabase():
    # Secrets are optional during local-only testing.
    try:
        url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
        key = st.secrets.get("SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
    except Exception:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_ANON_KEY", "")
    if url and key and create_client:
        return create_client(url, key)
    return None

def backend_name(sb):
    return "Supabase shared cloud leaderboard" if sb else "Local SQLite leaderboard (same server only)"

def save_result(sb, record):
    if sb:
        sb.table("submissions").upsert(record, on_conflict="id").execute()
    else:
        conn = local_db()
        conn.execute("""INSERT OR REPLACE INTO submissions
        (id,room,player,score,total,attempted,elapsed_seconds,submitted_at,answers_json)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (record["id"], record["room"], record["player"], record["score"], record["total"],
         record["attempted"], record["elapsed_seconds"], record["submitted_at"], record["answers_json"]))
        conn.commit()
        conn.close()

def fetch_results(sb, room):
    if sb:
        result = sb.table("submissions").select("*").eq("room", room).execute()
        rows = result.data or []
    else:
        conn = local_db()
        cur = conn.execute("""SELECT id,room,player,score,total,attempted,elapsed_seconds,submitted_at,answers_json
                              FROM submissions WHERE room=?""", (room,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        conn.close()
    # Keep each student's best result if they have restarted/re-submitted.
    best = {}
    for r in rows:
        key = (r.get("room", ""), r.get("player", "").strip().casefold())
        if key not in best or (int(r.get("score", 0)), -int(r.get("elapsed_seconds", 99999))) > (int(best[key].get("score", 0)), -int(best[key].get("elapsed_seconds", 99999))):
            best[key] = r
    rows = list(best.values())
    rows.sort(key=lambda r: (-int(r.get("score", 0)), int(r.get("elapsed_seconds", 99999)), r.get("submitted_at", "")))
    return rows

def result_record(sb, room, player, answers, started_at):
    correct = sum(1 for i, q in enumerate(QUESTIONS) if answers.get(str(i)) == q["answer"])
    attempted = sum(1 for i in range(TOTAL) if answers.get(str(i)) in LETTERS)
    elapsed = min(DURATION_SECONDS, max(0, int(time.time() - started_at)))
    # A stable ID means the same player updates their result instead of creating duplicates.
    identity = hashlib.sha256(f"{room.strip().upper()}::{player.strip().casefold()}".encode("utf-8")).hexdigest()[:24]
    return {
        "id": identity,
        "room": room.strip().upper(),
        "player": player.strip(),
        "score": int(correct),
        "total": int(TOTAL),
        "attempted": int(attempted),
        "elapsed_seconds": int(elapsed),
        "submitted_at": utc_now(),
        "answers_json": json.dumps(answers)
    }

def reset_student():
    for key in ["game_started", "game_started_at", "game_answers", "game_submitted", "game_name", "game_room", "game_id"]:
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if key.startswith("answer_radio_") or key.startswith("nav_"):
            st.session_state.pop(key, None)

sb = get_supabase()
if "view" not in st.session_state:
    st.session_state.view = "Play"
st.markdown("""
<div class="hero">
  <div style="font-size:2.3rem"></div>
  <h1>DATA SUFFICIENCY QUIZ</h1>
  <p>30 questions · 15 minutes · Live classroom leaderboard</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## Game menu")
    mode = st.radio("Choose a view", ["Play", "Live leaderboard", "Teacher control"], index=["Play","Live leaderboard","Teacher control"].index(st.session_state.view))
    st.session_state.view = mode
    st.markdown("---")
    st.caption(f"Backend: {backend_name(sb)}")
    if not sb:
        st.warning("For students on different devices, configure Supabase. Local SQLite only shares scores when everyone uses this same running server.")
    st.caption("Questions are based on the supplied Data Sufficiency practice sets.")

if st.session_state.view == "Play":
    if not st.session_state.get("game_started", False):
        c1,c2,c3 = st.columns(3)
        for col,val,label in [(c1,"30","Questions"),(c2,"15:00","Time limit"),(c3,"A–E","Answer choices")]:
            with col:
                st.markdown(f'<div class="metric"><div class="value">{val}</div><div class="label">{label}</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel"><h3> Rules of the challenge</h3><p style="font-size:1.05rem">A: Statement 1 alone is sufficient, but Statement 2 alone is not. <p> B: Statement 2 alone is sufficient, but Statement 1 alone is not.  <p> C: Both statements together are sufficient, but neither alone is sufficient.  <p> D: Each statement alone is sufficient. <p> E: Even both statements together are insufficient.  <p> Choose A, B, C, D or E.  <p> You can move between questions; answers save as you go.  <p> Your score is posted to the live leaderboard when you submit.</p><p class="small-note">Ranking: Highest score first; Ties are broken by faster completion time.</p></div>', unsafe_allow_html=True)
        with st.form("join_game"):
            name = st.text_input("Your name (or pair name)", placeholder="Use a unique name so your score is easy to identify")
            room = st.text_input("Classroom code", value=DEFAULT_ROOM, help="Everyone must use the same classroom code.")
            confirm = st.checkbox("I am ready to start my 15-minute attempt.")
            start = st.form_submit_button("JOIN & START", type="primary", use_container_width=True)
            if start:
                if not name.strip():
                    st.error("Please enter your name or pair name.")
                elif not room.strip():
                    st.error("Please enter the classroom code.")
                elif not confirm:
                    st.warning("Tick the confirmation box to begin.")
                else:
                    st.session_state.game_name = name.strip()[:80]
                    st.session_state.game_room = room.strip().upper()[:32]
                    st.session_state.game_started_at = time.time()
                    st.session_state.game_started = True
                    st.session_state.game_answers = {}
                    st.session_state.game_submitted = False
                    st.session_state.game_id = str(uuid.uuid4())
                    st.session_state.current_q = 0
                    st.rerun()
    elif not st.session_state.get("game_submitted", False):
        elapsed = max(0, int(time.time() - st.session_state.game_started_at))
        remaining = max(0, DURATION_SECONDS - elapsed)
        if remaining <= 0:
            record = result_record(sb, st.session_state.game_room, st.session_state.game_name, st.session_state.game_answers, st.session_state.game_started_at)
            save_result(sb, record)
            st.session_state.game_submitted = True
            st.session_state.game_record = record
            st.session_state.auto_submitted = True
            st.rerun()
        st_autorefresh(interval=1000, key="game_timer_refresh")
        mins,secs = divmod(remaining,60)
        answered = sum(1 for i in range(TOTAL) if st.session_state.game_answers.get(str(i)) in LETTERS)
        c1,c2,c3 = st.columns(3)
        with c1: st.markdown(f'<div class="metric"><div class="value" style="font-size:1.45rem"> {st.session_state.game_name}</div><div class="label">Player / pair</div></div>',unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="metric"><div class="value" style="color:{"#f87171" if remaining<=300 else "#facc15"}">{mins:02d}:{secs:02d}</div><div class="label">Time remaining</div></div>',unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="metric"><div class="value">{answered}/{TOTAL}</div><div class="label">Answered</div></div>',unsafe_allow_html=True)
        st.progress(answered/TOTAL, text=f"Progress: {answered} of {TOTAL} answered")
        nav = st.columns(10)
        for i in range(TOTAL):
            with nav[i%10]:
                label = f"✓ {i+1}" if st.session_state.game_answers.get(str(i)) in LETTERS else str(i+1)
                if st.button(label, key=f"nav_{i}", use_container_width=True):
                    st.session_state.current_q = i
                    st.rerun()
        idx = st.session_state.get("current_q",0)
        q = QUESTIONS[idx]
        st.markdown(f'<div class="panel"><div class="q-number">QUESTION {idx+1:02d} / {TOTAL} · {q["level"].upper()}</div><p><span style="display:inline-block;border-radius:999px;padding:.25rem .7rem;background:#facc1530;color:#fde68a;font-weight:800">{q["topic"]}</span></p><div class="question">{q["q"]}</div><div class="statement"><b>Statement (1)</b><br>{q["s1"]}</div><div class="statement"><b>Statement (2)</b><br>{q["s2"]}</div></div>',unsafe_allow_html=True)
        st.markdown("### Select your answer")
        current = st.session_state.game_answers.get(str(idx))
        selected = st.radio("Answer options", LETTERS, format_func=lambda x:f"{x}. {CHOICES[x]}", index=LETTERS.index(current) if current in LETTERS else None, key=f"answer_radio_{idx}", label_visibility="collapsed")
        if selected:
            st.session_state.game_answers[str(idx)] = selected
        a,b,c = st.columns(3)
        with a:
            if st.button("⬅ Previous", disabled=idx==0, use_container_width=True):
                st.session_state.current_q=idx-1; st.rerun()
        with b:
            if st.button("Next ➡", disabled=idx==TOTAL-1, type="primary", use_container_width=True):
                st.session_state.current_q=idx+1; st.rerun()
        with c:
            if st.button("🏁 SUBMIT MY ATTEMPT", type="primary", use_container_width=True):
                record = result_record(sb, st.session_state.game_room, st.session_state.game_name, st.session_state.game_answers, st.session_state.game_started_at)
                save_result(sb, record)
                st.session_state.game_submitted = True
                st.session_state.game_record = record
                st.session_state.auto_submitted = False
                st.rerun()
    else:
        record = st.session_state.game_record
        score = int(record["score"])
        pct = round(score/TOTAL*100)
        st.markdown("## Attempt submitted!")
        c1,c2,c3 = st.columns(3)
        with c1: st.markdown(f'<div class="metric"><div class="value">{score}/{TOTAL}</div><div class="label">Your score</div></div>',unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="metric"><div class="value">{pct}%</div><div class="label">Accuracy</div></div>',unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="metric"><div class="value">{record["attempted"]}/{TOTAL}</div><div class="label">Attempted</div></div>',unsafe_allow_html=True)
        st.success("Your score has been submitted to the classroom leaderboard.")
        if st.session_state.get("auto_submitted",False):
            st.warning("Time expired; your answers were submitted automatically.")
        if st.button("View live leaderboard", type="primary", use_container_width=True):
            st.session_state.view="Live leaderboard"; st.rerun()
        with st.expander("Review answers and explanations"):
            for i,q in enumerate(QUESTIONS):
                your = st.session_state.game_answers.get(str(i),"Not answered")
                mark = "✅" if your == q["answer"] else "❌"
                st.markdown(f"**{mark} Q{i+1}. {q['q']}**")
                st.markdown(f"Your answer: **{your}** · Correct answer: **{q['answer']} — {CHOICES[q['answer']]}**")
                st.info(q["why"])
        if st.button("Start a new attempt", use_container_width=True):
            reset_student(); st.rerun()

elif st.session_state.view == "Live leaderboard":
    room = st.text_input("Classroom code to display", value=st.session_state.get("game_room", DEFAULT_ROOM)).strip().upper()
    st_autorefresh(interval=5000, key="leaderboard_refresh")
    rows = fetch_results(sb, room)
    total_players = len(rows)
    top1,top2,top3 = st.columns(3)
    with top1: st.markdown(f'<div class="metric"><div class="value">{total_players}</div><div class="label">Submitted attempts</div></div>',unsafe_allow_html=True)
    with top2: st.markdown(f'<div class="metric"><div class="value">{max([int(r["score"]) for r in rows],default=0)}/{TOTAL}</div><div class="label">Top score</div></div>',unsafe_allow_html=True)
    with top3: st.markdown(f'<div class="metric"><div class="value">5 sec</div><div class="label">Refresh interval</div></div>',unsafe_allow_html=True)
    st.caption(f"Room: {room} · The board refreshes automatically. Students appear after submitting.")
    if not rows:
        st.info("No submissions yet. The leaderboard will populate when the first student submits.")
    else:
        display = []
        for i,r in enumerate(rows, start=1):
            elapsed = int(r.get("elapsed_seconds",0))
            display.append({"Rank": "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else i,
                            "Player / Pair": r.get("player",""),
                            "Score": f'{r.get("score",0)}/{r.get("total",TOTAL)}',
                            "Accuracy": f'{round(int(r.get("score",0))/TOTAL*100)}%',
                            "Attempted": f'{r.get("attempted",0)}/{TOTAL}',
                            "Time": f'{elapsed//60:02d}:{elapsed%60:02d}'})
        st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True, height=min(650, 44+len(display)*38))
        csv_rows = [{"Rank":i, "Player":r.get("player",""), "Score":r.get("score",0), "Total":r.get("total",TOTAL),
                     "Attempted":r.get("attempted",0), "Elapsed seconds":r.get("elapsed_seconds",0),
                     "Submitted at":r.get("submitted_at","")} for i,r in enumerate(rows,1)]
        st.download_button("⬇ Download leaderboard CSV", pd.DataFrame(csv_rows).to_csv(index=False), "classroom_leaderboard.csv", "text/csv")
    st.markdown('<p class="small-note">Ranking rule: score descending, then completion time ascending. Each player name appears once; a later better attempt replaces the previous result.</p>',unsafe_allow_html=True)

else:
    st.markdown("## Teacher control panel")
    st.markdown('<div class="panel"><h3>Classroom setup</h3><p>Give every student the same room code. Keep the leaderboard open on the projector in a separate browser or device. Students open the app on their own phones/laptops, enter their names and the room code, and start.</p><p class="small-note">For true cross-device sharing, connect the app to Supabase using the setup instructions in README.md. Local SQLite is suitable only when everyone connects to the same running server.</p></div>',unsafe_allow_html=True)
    room = st.text_input("Room code", value=DEFAULT_ROOM).strip().upper()
    rows = fetch_results(sb, room)
    c1,c2 = st.columns(2)
    with c1: st.metric("Submitted players", len(rows))
    with c2: st.metric("Current best score", f'{max([int(r["score"]) for r in rows],default=0)}/{TOTAL}')
    st.markdown("### Quick checklist")
    st.checkbox("Share the app URL with students")
    st.checkbox("Display the room code")
    st.checkbox("Ask students to use a unique name or pair name")
    st.checkbox("Open the Live leaderboard view on the projector")
    if st.button("🔄 Refresh teacher stats"):
        st.rerun()
