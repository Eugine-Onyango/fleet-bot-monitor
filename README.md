# ⚡ Fleet Bots Live Monitor Dashboard

A lightweight, real-time, mobile-first web dashboard to monitor your trading fleet bots (Fleet 1, Fleet 2, Over/Under) from anywhere on your phone or laptop.

## 🚀 Architecture: How it Works
1. **Droplet Pusher (`fleet_monitor_pusher.py`)**: Runs in the background on your DigitalOcean Droplet. Every 30 seconds, it grabs stats & simplified logs from your running Docker containers and pushes them via outbound HTTPS to a private GitHub Gist.
2. **Web Dashboard (`index.html`)**: Hosted for free on Vercel or GitHub Pages. Fetches the Gist data and displays live cards, P&L, win rates, and parsed log feeds with auto-refresh.

---

## 🛠️ Step 1: Create a GitHub Gist & Token (Takes 1 Minute)

1. **Create the Gist:**
   - Go to [gist.github.com](https://gist.github.com).
   - Filename: `fleet_status.json`
   - Content: `{}`
   - Click **Create secret gist**.
   - Note down the **Gist ID** from the URL (the long string of letters/numbers at the end: `https://gist.github.com/your-username/[GIST_ID]`).

2. **Generate a GitHub Personal Access Token (Classic):**
   - Go to [GitHub Settings -> Tokens (classic)](https://github.com/settings/tokens/new).
   - Note: `Fleet Bot Monitor`
   - Scopes: Check **`gist`** only.
   - Click **Generate token** and copy it.

---

## 💻 Step 2: Run the Pusher on Your Droplet

Open your **DigitalOcean Web Console** and run:

```bash
# 1. Download the pusher script
curl -o /root/fleet_monitor_pusher.py https://raw.githubusercontent.com/<YOUR-REPO>/main/fleet_monitor_pusher.py
# (Or paste the content of fleet_monitor_pusher.py into /root/fleet_monitor_pusher.py)

# 2. Run it in background with your credentials
nohup python3 -u /root/fleet_monitor_pusher.py > /root/pusher.log 2>&1 &
```
*(Tip: Replace `YOUR_GIST_ID_HERE` and `YOUR_GITHUB_TOKEN_HERE` inside the script or pass them as environment variables)*

To verify it is pushing successfully:
```bash
tail -f /root/pusher.log
```

---

## 🌐 Step 3: Deploy Dashboard to Vercel

1. Push this folder (`fleet-monitor-dashboard`) to a new repository on your GitHub (e.g. `fleet-bot-monitor`).
2. Go to [vercel.com](https://vercel.com) and click **Add New Project**.
3. Import your repository and click **Deploy**.
4. Open the generated Vercel URL on your phone or laptop!
5. Click the **Settings (gear icon)** at the top right, enter your **Gist ID**, and click **Save & Sync**.
