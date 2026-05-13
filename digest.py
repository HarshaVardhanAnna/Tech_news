"""
Tech Digest v2 — AI-Powered Daily News Aggregator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pipeline:
  1. FETCH   — Collect ALL articles from all sources (no hard cap)
  2. DEDUPE  — Remove duplicate URLs
  3. FILTER  — Quick keyword pre-filter (cuts obviously off-topic noise)
  4. AI SCORE — Gemini reads title+summary, scores 1-10 for relevance
  5. THRESHOLD — Keep only score >= 7 (quality gate, not count gate)
  6. EMAIL   — Send beautifully formatted digest
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import time
import smtplib
import requests
import feedparser
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# Edit this section to personalise your digest
# ═══════════════════════════════════════════════

# Used only for pre-filtering (broad net — keeps anything remotely relevant)
# Gemini handles the deep relevance scoring after this
BROAD_KEYWORDS = [
    # Languages
    "python", "golang", "go ", "rust", "sql",
    # Data domain
    "data engineering", "data pipeline", "data science", "data warehouse",
    "etl", "elt", "dbt", "airflow", "spark", "kafka", "flink",
    "duckdb", "lakehouse", "iceberg", "delta lake", "hudi",
    # ML / AI
    "machine learning", "deep learning", "llm", "ai ", "artificial intelligence",
    "neural network", "mlops", "vector", "embedding", "fine-tun",
    # Backend / infra
    "backend", "api", "fastapi", "database", "postgresql", "redis",
    "docker", "kubernetes", "microservice", "distributed",
    # Tools & libraries
    "pandas", "polars", "pydantic", "sqlalchemy", "celery",
    # General engineering
    "software engineer", "system design", "architecture", "performance",
    "open source", "benchmark"
]

REDDIT_SUBREDDITS = [
    "dataengineering", "MachineLearning", "Python",
    "golang", "LocalLLaMA", "datascience",
    "programming", "softwareengineering", "devops"
]

RSS_FEEDS = [
    "https://dev.to/feed",
    "https://towardsdatascience.com/feed",
    "https://martinfowler.com/feed.atom",
    "https://blog.pragmaticengineer.com/rss/",
    "https://www.databricks.com/feed",
    "https://engineering.fb.com/feed/",
    "https://netflixtechblog.com/feed",
    "https://blog.bytebytego.com/feed",
]

# Gemini scores each article 1-10
# Only articles >= this threshold reach your inbox
AI_SCORE_THRESHOLD = 7

# Your profile — this is sent to Gemini so it scores
# articles relative to YOU, not a generic developer
MY_PROFILE = """
Software Engineer, 1 year experience.
Skills: Python, Go, SQL, Data Engineering, Data Science, ML Engineering, Backend Development.
Interests: Data pipelines, ETL/ELT tools, LLMs, system design, backend architecture,
           open source tools, database internals, performance optimization.
Level: Intermediate — wants real technical depth, not beginner tutorials.
Goal: Stay current with industry trends, discover important tools/releases,
      learn things worth sharing on LinkedIn.
"""


# ═══════════════════════════════════════════════
# SECTION 2 — FETCHERS (no hard caps — collect everything)
# ═══════════════════════════════════════════════

def _keyword_match(text: str) -> bool:
    """Broad pre-filter — true if any keyword found in text."""
    text = text.lower()
    return any(kw in text for kw in BROAD_KEYWORDS)


def fetch_hackernews() -> list[dict]:
    """
    HackerNews Firebase REST API.
    Fetches top 100 story IDs, then fetches each story.
    No cap — keyword pre-filter decides what passes.
    """
    articles = []
    try:
        top_ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10
        ).json()[:100]  # top 100 stories (was 60 before, no arbitrary cap now)

        for story_id in top_ids:
            try:
                story = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                    timeout=5
                ).json()

                if not story or story.get("type") != "story":
                    continue

                title = story.get("title", "")
                # Broad keyword pre-filter — passes anything loosely related
                if _keyword_match(title):
                    articles.append({
                        "title": title,
                        "summary": "",          # HN has no summary, Gemini uses title only
                        "url": story.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                        "community_score": story.get("score", 0),
                        "source": "Hacker News",
                        "comments_url": f"https://news.ycombinator.com/item?id={story_id}",
                        # AI fields — populated later by score_with_gemini()
                        "ai_score": 0,
                        "ai_reason": ""
                    })
            except Exception:
                continue

    except Exception as e:
        print(f"  [HackerNews] Error: {e}")

    return articles


def fetch_devto() -> list[dict]:
    """
    Dev.to public REST API — no key needed.
    Fetches top articles per tag. `seen` set prevents duplicates
    when the same article ranks under multiple tags.
    """
    articles = []
    seen_ids = set()
    tags = [
        "python", "go", "sql", "machinelearning", "dataengineering",
        "backend", "database", "devops", "ai", "llm"
    ]

    try:
        for tag in tags:
            res = requests.get(
                f"https://dev.to/api/articles?tag={tag}&per_page=10&top=1",
                timeout=10
            )
            if res.status_code != 200:
                continue

            for article in res.json():
                aid = article.get("id")
                if aid in seen_ids:
                    continue
                seen_ids.add(aid)

                title = article.get("title", "")
                summary = article.get("description", "")

                if _keyword_match(title + " " + summary):
                    articles.append({
                        "title": title,
                        "summary": summary,
                        "url": article.get("url", ""),
                        "community_score": article.get("positive_reactions_count", 0),
                        "source": "Dev.to",
                        "comments_url": article.get("url", ""),
                        "ai_score": 0,
                        "ai_reason": ""
                    })

            time.sleep(0.3)  # gentle rate limiting between tag requests

    except Exception as e:
        print(f"  [Dev.to] Error: {e}")

    return articles


def fetch_reddit() -> list[dict]:
    """
    Reddit public JSON API — no key needed.
    User-Agent header is required (Reddit blocks requests without it).
    Fetches hot posts from each subreddit.
    """
    articles = []
    headers = {"User-Agent": "TechDigestPersonalBot/2.0"}

    try:
        for sub in REDDIT_SUBREDDITS:
            try:
                res = requests.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=15",
                    headers=headers,
                    timeout=10
                )
                if res.status_code != 200:
                    continue

                posts = res.json().get("data", {}).get("children", [])
                for post in posts:
                    d = post.get("data", {})
                    title = d.get("title", "")
                    summary = d.get("selftext", "")[:300]  # first 300 chars of post body

                    if _keyword_match(title + " " + summary):
                        articles.append({
                            "title": title,
                            "summary": summary,
                            "url": d.get("url") or f"https://reddit.com{d.get('permalink', '')}",
                            "community_score": d.get("score", 0),
                            "source": f"r/{sub}",
                            "comments_url": f"https://reddit.com{d.get('permalink', '')}",
                            "ai_score": 0,
                            "ai_reason": ""
                        })

                time.sleep(0.5)  # Reddit rate limit — be respectful

            except Exception as e:
                print(f"  [Reddit r/{sub}] Error: {e}")
                continue

    except Exception as e:
        print(f"  [Reddit] Error: {e}")

    return articles


def fetch_rss_feeds() -> list[dict]:
    """
    RSS/Atom feed parser.
    feedparser.parse() handles both RSS and Atom formats transparently.
    entry.get("summary") contains the article description/excerpt.
    """
    articles = []

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            feed_name = feed.feed.get("title", feed_url)

            for entry in feed.entries[:15]:  # up to 15 per feed, keyword filter narrows it
                title = entry.get("title", "")
                # Clean summary — strip HTML tags roughly
                raw_summary = entry.get("summary", entry.get("description", ""))
                summary = raw_summary[:500] if raw_summary else ""

                if _keyword_match(title + " " + summary):
                    articles.append({
                        "title": title,
                        "summary": summary,
                        "url": entry.get("link", feed_url),
                        "community_score": 0,
                        "source": feed_name,
                        "comments_url": entry.get("link", feed_url),
                        "ai_score": 0,
                        "ai_reason": ""
                    })

        except Exception as e:
            print(f"  [RSS {feed_url}] Error: {e}")

    return articles


# ═══════════════════════════════════════════════
# SECTION 3 — GEMINI AI MIDDLEWARE
# The intelligence layer — scores articles 1-10
# ═══════════════════════════════════════════════

GEMINI_CHUNK_SIZE  = 30    # articles per API call — reduced to keep output well within limits
GEMINI_MAX_TOKENS  = 16384 # output tokens per chunk — generous budget so JSON never truncates
GEMINI_MAX_RETRIES = 2     # retry a failing chunk this many times before giving up


def _sanitize(text: str) -> str:
    """
    Cleans text before embedding in prompt to prevent broken JSON responses.

    WHY: Article titles with special chars corrupt Gemini JSON output.
    Example problem:
      Title: He said "Python is dead"
      Gemini output: {"reason": "He said "Python is dead""} <- broken JSON

    We strip: double-quotes (-> single), backslashes, newlines, non-ASCII.
    """
    if not text:
        return ""
    text = text.replace("\\", "")
    text = text.replace('"', "'")
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = text.encode("ascii", errors="ignore").decode()
    text = " ".join(text.split())
    return text.strip()


def _score_chunk(api_key: str, chunk: list[dict], offset: int) -> list[dict]:
    """
    Scores a single chunk of articles via one Gemini API call.

    offset = the starting index of this chunk in the full article list.
    Gemini sees local indices 0..N within the chunk; we add offset when
    writing scores back so they map correctly to the full list.
    """
    article_lines = []
    for i, a in enumerate(chunk):
        title   = _sanitize(a["title"])
        summary = _sanitize(a["summary"][:150]) if a["summary"] else "No summary"
        article_lines.append(f'{i}. TITLE: {title}\n   SUMMARY: {summary}')

    articles_text = "\n\n".join(article_lines)

    prompt = f"""You are a relevance scoring engine for a personal tech news digest.

READER PROFILE:
{MY_PROFILE}

TASK:
Score each article below from 1 to 10 based on how relevant, valuable, and interesting
it would be for this specific reader. Be strict — only genuinely useful articles should
score 7 or above.

SCORING GUIDE:
9-10 → Must-read: major release, breakthrough, or industry shift directly in their stack.
       Reserved for truly exceptional content. Expect 1-2 per batch at most.
7-8  → Genuinely worth reading: real technical depth, directly relevant tool/pattern/concept.
       Expect 20-30% of articles to score here on a good day.
5-6  → Marginal: loosely related, surface-level, or not specific enough to their stack.
3-4  → Weak: off-topic, clickbait title, opinion without substance, too basic.
1-2  → Irrelevant: wrong domain, no technical value, news/politics/lifestyle.

BE STRICT. Most articles should score 4-6. A batch of 30 should yield at most 8-10 articles
scoring 7+. If you find yourself scoring more than 10 articles at 7+ in a batch of 30,
you are being too generous — re-calibrate downward.

ARTICLES TO SCORE:
{articles_text}

RESPONSE FORMAT:
Return ONLY a valid JSON array. No explanation, no markdown, no extra text.
Each object must have exactly: "index" (int), "score" (int 1-10), "reason" (max 12 words).

Example:
[
  {{"index": 0, "score": 8, "reason": "Covers DuckDB 2.0 release with real benchmark data"}},
  {{"index": 1, "score": 3, "reason": "Basic Python tutorial, too introductory for this level"}}
]
"""

    res = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": GEMINI_MAX_TOKENS
            }
        },
        timeout=90
    )

    if res.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {res.status_code}: {res.text[:200]}")

    response_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]

    # responseMimeType="application/json" guarantees clean JSON — parse directly
    # Still strip just in case, but this should never be needed now
    clean = response_text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()

    scores = json.loads(clean)

    # Re-map local chunk indices → global article indices using offset
    for item in scores:
        item["index"] = item["index"] + offset

    return scores


def score_with_gemini(articles: list[dict]) -> list[dict]:
    """
    Scores all articles by splitting them into chunks of GEMINI_CHUNK_SIZE.

    WHY CHUNKING?
    - 211 articles in one prompt generates ~12k+ output tokens
    - With maxOutputTokens=4096 the JSON was truncated mid-string → parse error
    - Chunks of 50 articles need ~3k output tokens each — well within limits
    - Each chunk gets its own API call; results are merged back into articles[]

    OFFSET TRICK:
    Each chunk uses local indices 0..49 so the prompt stays clean.
    We add the chunk's starting position (offset) back when merging,
    so scores correctly map to the full article list.
    """
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("  ⚠️  No GEMINI_API_KEY — skipping AI scoring, keeping all articles")
        for a in articles:
            a["ai_score"] = 5
            a["ai_reason"] = "AI scoring skipped — no API key"
        return articles

    # Split articles into chunks
    chunks = [
        articles[i : i + GEMINI_CHUNK_SIZE]
        for i in range(0, len(articles), GEMINI_CHUNK_SIZE)
    ]
    total_chunks = len(chunks)
    print(f"  🤖 Scoring {len(articles)} articles in {total_chunks} chunk(s) of ≤{GEMINI_CHUNK_SIZE}...")

    all_scores = []   # flat list of {index, score, reason} across all chunks

    for chunk_num, chunk in enumerate(chunks, start=1):
        offset = (chunk_num - 1) * GEMINI_CHUNK_SIZE
        success = False
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                label = f"articles {offset+1}-{offset+len(chunk)}"
                if attempt == 1:
                    print(f"     Chunk {chunk_num}/{total_chunks} — {label}")
                else:
                    print(f"     Chunk {chunk_num}/{total_chunks} — retry {attempt}/{GEMINI_MAX_RETRIES}")
                chunk_scores = _score_chunk(api_key, chunk, offset)
                all_scores.extend(chunk_scores)
                success = True
                break  # chunk succeeded — move to next chunk
            except RuntimeError as e:
                # RuntimeError is raised by _score_chunk for HTTP errors
                is_rate_limit = "429" in str(e)
                err_type = "rate limit (429)" if is_rate_limit else "HTTP error"
                print(f"     ⚠️  Chunk {chunk_num} {err_type} (attempt {attempt}): {str(e)[:80]}")
                if attempt < GEMINI_MAX_RETRIES:
                    wait = 30 if is_rate_limit else 2 * attempt  # 429 needs a real wait
                    print(f"     ⏳ Waiting {wait}s before retry...")
                    time.sleep(wait)
                else:
                    print(f"     ❌ Chunk {chunk_num} failed after {GEMINI_MAX_RETRIES} attempts — scoring as 5")
                    for i in range(len(chunk)):
                        all_scores.append({"index": offset + i, "score": 5, "reason": "Scoring failed"})
            except json.JSONDecodeError as e:
                print(f"     ⚠️  Chunk {chunk_num} JSON error (attempt {attempt}): {str(e)[:80]}")
                if attempt < GEMINI_MAX_RETRIES:
                    time.sleep(3)
                else:
                    print(f"     ❌ Chunk {chunk_num} failed after {GEMINI_MAX_RETRIES} attempts — scoring as 5")
                    for i in range(len(chunk)):
                        all_scores.append({"index": offset + i, "score": 5, "reason": "JSON parse error"})
            except Exception as e:
                print(f"     ⚠️  Chunk {chunk_num} error (attempt {attempt}): {str(e)[:80]}")
                if attempt < GEMINI_MAX_RETRIES:
                    time.sleep(3)
                else:
                    print(f"     ❌ Chunk {chunk_num} failed after {GEMINI_MAX_RETRIES} attempts — scoring as 5")
                    for i in range(len(chunk)):
                        all_scores.append({"index": offset + i, "score": 5, "reason": "Scoring failed"})

        if success and chunk_num < total_chunks:
            time.sleep(4)  # 4s between chunks — prevents rate limiting on consecutive calls

    # Write all scores back to articles by global index
    score_map = {item["index"]: item for item in all_scores}
    for i, article in enumerate(articles):
        if i in score_map:
            article["ai_score"] = score_map[i]["score"]
            article["ai_reason"] = score_map[i]["reason"]
        else:
            article["ai_score"] = 5
            article["ai_reason"] = "Not scored by AI"

    high = sum(1 for a in articles if a["ai_score"] >= AI_SCORE_THRESHOLD)
    print(f"  ✅ Done — {len(all_scores)} scored → {high} passed threshold (≥{AI_SCORE_THRESHOLD})")

    return articles

    return articles


# ═══════════════════════════════════════════════
# SECTION 4 — EMAIL BUILDER
# Renders scored articles as a formatted HTML email
# ═══════════════════════════════════════════════

def score_badge(score: int) -> str:
    """Returns a colored score badge based on AI score."""
    if score >= 9:
        color, bg = "#ffffff", "#16a34a"  # green — must read
    elif score >= 7:
        color, bg = "#ffffff", "#2563eb"  # blue — worth reading
    else:
        color, bg = "#ffffff", "#64748b"  # grey — marginal
    return (
        f'<span style="background:{bg}; color:{color}; font-size:10px; font-weight:700;'
        f'padding:2px 7px; border-radius:10px; letter-spacing:0.5px;">AI {score}/10</span>'
    )


def group_by_source(articles: list[dict]) -> dict:
    grouped = {}
    for a in articles:
        grouped.setdefault(a["source"], []).append(a)
    # Sort each group by ai_score descending
    for src in grouped:
        grouped[src].sort(key=lambda x: x["ai_score"], reverse=True)
    return grouped


def build_html_email(articles: list[dict], raw_count: int, scored_count: int) -> str:
    today = datetime.now().strftime("%A, %d %B %Y")
    grouped = group_by_source(articles)

    source_icons = {
        "Hacker News": "🔶", "Dev.to": "💻",
        "r/": "🔴", "Towards": "📊", "Netflix": "🎬",
        "Pragmatic": "⚙️", "Databricks": "🧱", "Facebook": "📘"
    }

    def get_icon(source):
        return next((v for k, v in source_icons.items() if k in source), "📰")

    sections_html = ""
    for source, items in grouped.items():
        icon = get_icon(source)
        items_html = ""
        for item in items:
            badge = score_badge(item["ai_score"])
            reason_html = (
                f'<div style="color:#94a3b8; font-size:11px; margin-top:3px; font-style:italic;">'
                f'💡 {item["ai_reason"]}</div>'
                if item["ai_reason"] else ""
            )
            community_html = (
                f'<span style="color:#475569; font-size:11px;">⬆ {item["community_score"]}</span>&nbsp;&nbsp;'
                if item["community_score"] else ""
            )
            discussion_html = (
                f'<a href="{item["comments_url"]}" style="color:#475569; font-size:11px; text-decoration:none;">💬 Discussion</a>'
                if item["comments_url"] != item["url"] else ""
            )

            items_html += f"""
            <tr>
              <td style="padding:12px 0; border-bottom:1px solid #1e293b;">
                <div style="display:flex; align-items:flex-start; gap:8px; margin-bottom:4px;">
                  {badge}
                  <a href="{item['url']}"
                     style="color:#e2e8f0; font-size:14px; font-weight:600;
                            text-decoration:none; line-height:1.5; flex:1;">
                    {item['title']}
                  </a>
                </div>
                {reason_html}
                <div style="margin-top:6px;">
                  {community_html}{discussion_html}
                </div>
              </td>
            </tr>"""

        sections_html += f"""
        <tr><td style="padding:24px 0 8px 0;">
          <div style="color:#64748b; font-size:11px; font-weight:700;
               text-transform:uppercase; letter-spacing:2px; border-left:3px solid #38bdf8;
               padding-left:10px;">{icon} {source}</div>
        </td></tr>
        {items_html}"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background:#060d1a; font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#060d1a; padding:32px 16px;">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0"
             style="max-width:620px; width:100%;">

        <!-- ── HEADER ── -->
        <tr><td style="background:linear-gradient(135deg,#0f172a 0%,#1a1040 100%);
                border-radius:16px 16px 0 0; padding:32px 36px;
                border-bottom:2px solid #38bdf8;">
          <div style="color:#38bdf8; font-size:10px; font-weight:800;
               text-transform:uppercase; letter-spacing:4px;">
            🧠 AI-Curated Tech Digest
          </div>
          <div style="color:#f8fafc; font-size:24px; font-weight:800; margin-top:8px;">
            {today}
          </div>
          <div style="margin-top:14px; display:flex; gap:16px;">
            <span style="background:#1e293b; color:#94a3b8; font-size:11px;
                  padding:4px 12px; border-radius:20px;">
              📥 {raw_count} fetched
            </span>
            <span style="background:#1e293b; color:#94a3b8; font-size:11px;
                  padding:4px 12px; border-radius:20px;">
              🤖 {scored_count} AI-scored
            </span>
            <span style="background:#1e3a5f; color:#38bdf8; font-size:11px;
                  padding:4px 12px; border-radius:20px; font-weight:700;">
              ✅ {len(articles)} delivered
            </span>
          </div>
        </td></tr>

        <!-- ── PIPELINE INFO BAR ── -->
        <tr><td style="background:#0d1829; padding:10px 36px;
                border-bottom:1px solid #1e293b;">
          <div style="color:#475569; font-size:11px;">
            Pipeline: Fetch → Keyword pre-filter → 
            <span style="color:#38bdf8;">Gemini AI scored</span> → 
            Threshold ≥{AI_SCORE_THRESHOLD} → Your inbox
          </div>
        </td></tr>

        <!-- ── ARTICLES ── -->
        <tr><td style="background:#0f172a; padding:8px 36px 36px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {sections_html}
          </table>
        </td></tr>

        <!-- ── FOOTER ── -->
        <tr><td style="background:#060d1a; border-radius:0 0 16px 16px;
                padding:20px 36px; border-top:1px solid #1e293b;">
          <div style="color:#334155; font-size:11px; text-align:center; line-height:1.8;">
            Your personal AI-curated tech digest · Python + Gemini 1.5 Flash 🐍🤖<br>
            <span style="color:#1e3a5f;">14-day LinkedIn post cycle running</span>
          </div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ═══════════════════════════════════════════════
# SECTION 5 — EMAIL SENDER
# ═══════════════════════════════════════════════

def send_email(html_body: str, article_count: int):
    sender   = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")

    if not all([sender, password, receiver]):
        print("\n  ⚠️  Email credentials not set — saving to digest_output.html")
        with open("digest_output.html", "w", encoding="utf-8") as f:
            f.write(html_body)
        print("  ✅ Saved to digest_output.html — open in browser to preview")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"🧠 Tech Digest — {datetime.now().strftime('%d %b')} "
        f"| {article_count} AI-curated articles"
    )
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, receiver, msg.as_string())
        print(f"\n  ✅ Digest sent → {receiver}")
    except Exception as e:
        print(f"\n  ❌ Email failed: {e}")


# ═══════════════════════════════════════════════
# SECTION 6 — PIPELINE ORCHESTRATOR
# Ties all stages together in sequence
# ═══════════════════════════════════════════════

def run():
    print(f"\n{'━'*52}")
    print(f"  🧠 Tech Digest v2  ·  {datetime.now().strftime('%d %b %Y  %H:%M')}")
    print(f"{'━'*52}")

    # ── STAGE 1: FETCH ──────────────────────────
    print("\n📡  STAGE 1 — Fetching articles...")
    all_articles = []

    print("  → Hacker News")
    all_articles.extend(fetch_hackernews())

    print("  → Dev.to")
    all_articles.extend(fetch_devto())

    print("  → Reddit")
    all_articles.extend(fetch_reddit())

    print("  → RSS Feeds")
    all_articles.extend(fetch_rss_feeds())

    print(f"  Total fetched (before dedup): {len(all_articles)}")

    # ── STAGE 2: DEDUPLICATE ────────────────────
    print("\n🔁  STAGE 2 — Deduplicating...")
    seen_urls = set()
    unique = []
    for a in all_articles:
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)
    print(f"  Unique articles after dedup: {len(unique)}")
    raw_count = len(unique)

    # ── STAGE 3: KEYWORD PRE-FILTER ────────────
    # Already done inside each fetcher via _keyword_match()
    # This stage just reports it
    print(f"\n🔍  STAGE 3 — Keyword pre-filter already applied in fetchers")
    print(f"  Articles entering AI stage: {len(unique)}")

    # ── STAGE 4: AI SCORING ─────────────────────
    print(f"\n🤖  STAGE 4 — Gemini AI scoring...")
    scored = score_with_gemini(unique)
    scored_count = len(scored)

    # ── STAGE 5: THRESHOLD FILTER ───────────────
    print(f"\n🎯  STAGE 5 — Applying quality threshold (score ≥ {AI_SCORE_THRESHOLD})...")
    final = [a for a in scored if a["ai_score"] >= AI_SCORE_THRESHOLD]
    # Sort by ai_score descending within final list
    final.sort(key=lambda x: x["ai_score"], reverse=True)
    print(f"  Articles passing threshold: {len(final)}")

    if not final:
        print("\n  ⚠️  No articles passed the threshold today.")
        print("  Consider lowering AI_SCORE_THRESHOLD in config, or check your sources.")
        return

    # ── STAGE 6: BUILD + SEND EMAIL ─────────────
    print(f"\n📧  STAGE 6 — Building and sending email...")
    html = build_html_email(final, raw_count, scored_count)
    send_email(html, len(final))

    # ── SUMMARY ─────────────────────────────────
    print(f"\n{'━'*52}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Fetched: {raw_count}  →  AI-scored: {scored_count}  →  Delivered: {len(final)}")
    print(f"{'━'*52}\n")


if __name__ == "__main__":
    run()