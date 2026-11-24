# VULPHEX on Kaggle (owner's request, Nov 24 2026): train the bots in your BROWSER, on Kaggle's free GPU, under YOUR
# own account — no key shared with anyone. It downloads VULPHEX, loads the uncensored ancestor model, has the bots
# STUDY every repo (learn each one's technique into the neural network), then serves the Arena dashboard over a private
# link so you watch them train and talk to the brain. Safe: training is against the local practice range only.
#
# Run it: new Kaggle notebook, Accelerator = GPU T4 x2, Internet = on, one cell:
#   !curl -fsSL https://raw.githubusercontent.com/blackadmen732-wq/vulphex/main/arena/kaggle.py -o k.py && python -u k.py
import os, re, subprocess, sys, threading, time

REPO = "https://github.com/blackadmen732-wq/vulphex"
DIR = "/kaggle/working/vulphex"
MODEL = os.environ.get("COACH_MODEL", "Goekdeniz-Guelmez/Josiefied-Qwen2.5-1.5B-Instruct-abliterated-v1")
PORT = 3006


def sh(cmd, **kw): return subprocess.run(cmd, shell=True, check=True, **kw)


def main():
    if not os.path.isdir(DIR): sh(f"git clone --depth 1 {REPO} {DIR}")
    else: sh(f"cd {DIR} && git pull -q || true")
    sh("pip install -q transformers accelerate >/dev/null 2>&1 || true")
    env = {**os.environ, "COACH_MODEL": MODEL, "VULPHEX_ARENA_PORT": str(PORT)}

    # 1) STUDY: the bots read every repo and learn its technique into the brain
    print("Studying the repos (learning each tool's technique)...", flush=True)
    study = subprocess.run([sys.executable, "security/artex.py", "study"], cwd=DIR, env=env, capture_output=True, text=True, timeout=3600)
    print(study.stdout[-1500:], flush=True)

    # 2) serve the Arena dashboard
    srv = subprocess.Popen([sys.executable, "arena/server.py"], cwd=DIR, env=env)
    for _ in range(40):
        try:
            import urllib.request; urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/state", timeout=2); break
        except Exception: time.sleep(0.5)

    # 3) open a private browser link
    if not os.path.exists("/tmp/cloudflared"):
        sh("curl -fsSL -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x /tmp/cloudflared")
    tun = subprocess.Popen(["/tmp/cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    for line in tun.stdout:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m: url = m.group(0); break
    threading.Thread(target=lambda: [None for _ in tun.stdout], daemon=True).start()
    print("\n" + "=" * 70)
    print("VULPHEX ARENA IS LIVE. Open this in your browser:\n")
    print(f"    {url}\n")
    print("Pick a squad, press Train, watch them learn, and chat to the ancestor brain.")
    print("=" * 70, flush=True)
    srv.wait()


if __name__ == "__main__":
    main()
