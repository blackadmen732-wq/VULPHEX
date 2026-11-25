# VULPHEX persistence (owner's request, Nov 2026): keep what the bots learn ACROSS Kaggle restarts. The brain, the
# studied repos and the findings all live in security/vulphex.db, which is wiped every time a Kaggle notebook stops.
# This module snapshots that whole SQLite file into the owner's Supabase (one row, base64) and restores it on startup,
# so training never starts from zero again ("fix their space"). Stdlib only; it NO-OPS cleanly when Supabase isn't
# configured, so local/offline runs are unaffected.
#
# Setup (once): a table in Supabase ->
#   create table if not exists public.vulphex_state (id text primary key, blob text, updated timestamptz default now());
# Then set two env vars (Kaggle Secrets) for the run:
#   SUPABASE_URL = https://<project-ref>.supabase.co     SUPABASE_KEY = <service_role key>
import base64, json, os, urllib.request

TABLE = "vulphex_state"
ROW_ID = "main"


def _conf():
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    return (url, key) if url and key else (None, None)


def enabled():
    return _conf()[0] is not None


def _req(method, path, body=None):
    url, key = _conf()
    if not url: return None
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method,
                                 headers={"apikey": key, "authorization": "Bearer " + key,
                                          "content-type": "application/json", "prefer": "resolution=merge-duplicates"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def restore(db_path):
    """If a snapshot exists in Supabase and there's no local DB yet, write it to db_path. Returns True if restored.
    Never raises — a failure just means we start fresh locally."""
    if not enabled() or os.path.exists(db_path): return False
    try:
        rows = _req("GET", f"/rest/v1/{TABLE}?id=eq.{ROW_ID}&select=blob")
        if rows and rows[0].get("blob"):
            with open(db_path, "wb") as f: f.write(base64.b64decode(rows[0]["blob"]))
            return True
    except Exception:
        return False
    return False


def snapshot(db_path):
    """Upload the current DB file to Supabase (upsert the single state row). Returns True on success. Never raises."""
    if not enabled() or not os.path.exists(db_path): return False
    try:
        with open(db_path, "rb") as f: blob = base64.b64encode(f.read()).decode()
        _req("POST", f"/rest/v1/{TABLE}", {"id": ROW_ID, "blob": blob})
        return True
    except Exception:
        return False
