# 📰 Tech Digest — Daily Tech News to Your Inbox

A personal daily digest that scrapes HackerNews, Dev.to, Reddit, and RSS feeds
for Python, Go, SQL, Data Engineering, ML, Backend news — and emails it to you.
Built to help you build a LinkedIn posting habit every 2 weeks.

---

## 🗂 Project Structure

```
tech-digest/
├── digest.py          ← Main script (fetch + email)
├── requirements.txt   ← Python dependencies
├── .env.example       ← Config template
├── .env               ← Your actual config (never commit this!)
└── README.md
```

---

## ⚙️ Setup (One Time Only)

### Step 1 — Clone / Download the project
Put the files in a folder on your machine, e.g. `~/projects/tech-digest/`

### Step 2 — Install Python dependencies
```bash
cd ~/projects/tech-digest
pip install -r requirements.txt
```

### Step 3 — Set up Gmail App Password
This is the most important step. You need a special password for the script.

1. Go to your Google Account → **Security**
2. Make sure **2-Step Verification is ON**
3. Search for **"App Passwords"** (or go to https://myaccount.google.com/apppasswords)
4. Select app: **Mail** → Select device: **Other** → Name it "Tech Digest"
5. Google gives you a 16-character password like `abcd efgh ijkl mnop`
6. Copy it (you'll only see it once)

### Step 4 — Create your .env file
```bash
cp .env.example .env
```
Open `.env` and fill in:
```
EMAIL_SENDER=your_gmail@gmail.com
EMAIL_PASSWORD=abcdefghijklmnop       ← the 16-char app password (no spaces)
EMAIL_RECEIVER=your_email@gmail.com   ← where you want to receive it
```

### Step 5 — Test it manually
```bash
python digest.py
```
Check your inbox! You should receive a digest email within seconds.

---

## ⏰ Automate It (Run Daily)

### On Mac/Linux — Using Cron
Run every day at 8:00 AM:

```bash
# Open crontab editor
crontab -e

# Add this line (adjust the path to where your project is)
0 8 * * * cd /Users/yourname/projects/tech-digest && python digest.py >> digest.log 2>&1
```

To check if it's saved:
```bash
crontab -l
```

### On Windows — Using Task Scheduler
1. Open **Task Scheduler** → Create Basic Task
2. Name: "Tech Digest"
3. Trigger: **Daily** at 8:00 AM
4. Action: **Start a program**
5. Program: `python`
6. Arguments: `C:\path\to\tech-digest\digest.py`
7. Start in: `C:\path\to\tech-digest\`

### Cloud Option — Free Deployment (Recommended for reliability)
Use **GitHub Actions** (free, runs in cloud, no need to keep your laptop on):

Create `.github/workflows/digest.yml`:
```yaml
name: Daily Tech Digest

on:
  schedule:
    - cron: '0 3 * * *'   # 8:30 AM IST = 3:00 AM UTC
  workflow_dispatch:        # allows manual trigger

jobs:
  send-digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python digest.py
        env:
          EMAIL_SENDER: ${{ secrets.EMAIL_SENDER }}
          EMAIL_PASSWORD: ${{ secrets.EMAIL_PASSWORD }}
          EMAIL_RECEIVER: ${{ secrets.EMAIL_RECEIVER }}
```

Then in your GitHub repo → **Settings → Secrets → Actions** → add the 3 secrets.
Push this file and it runs automatically every day. 100% free.

---

## 🎯 Your 14-Day LinkedIn Workflow

```
Day 1-13:  Digest arrives in inbox daily
           → Star/save interesting articles
           → Note any good learnings from work

Day 14:    Come to Claude with:
           - "Here are my saved links from 2 weeks: [paste links]"
           - "I learned X at work this week"
           → Claude helps you write one focused LinkedIn post
```

---

## 🔧 Customization

### Add more keywords (in digest.py)
```python
KEYWORDS = [
    "python", "golang", ...
    "your_new_keyword_here"    ← just add here
]
```

### Add more RSS feeds
```python
RSS_FEEDS = [
    ...
    "https://yourfavoriteblog.com/feed"   ← add any blog's RSS URL
]
```

### Add more subreddits
```python
REDDIT_SUBREDDITS = [
    ...
    "devops", "kubernetes"   ← add subreddit names
]
```

---

## 🚨 Troubleshooting

| Problem | Fix |
|---|---|
| `SMTPAuthenticationError` | Wrong app password — regenerate it |
| `No email received` | Check spam folder |
| `0 articles fetched` | Reddit/HN might be rate-limiting, retry in 10 min |
| Script runs but no email | Check .env has no extra spaces |
| Cron not working | Use absolute paths in cron, check `digest.log` |

---

## 💡 What to Post on LinkedIn (Ideas)

After 14 days of reading, your post could be about:
- A pattern you noticed ("Every ML post this week mentioned LLM fine-tuning — here's why")
- A tool comparison ("dbt vs SQLMesh — what the community is saying")
- A lesson from your job ("How I debugged a slow SQL query at work")
- A "TIL" post ("TIL Python's walrus operator can simplify while loops")

---

Built for personal use. Python 3.9+. No paid APIs needed.
