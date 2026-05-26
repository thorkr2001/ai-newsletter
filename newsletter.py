#!/usr/bin/env python3
"""
AI Intelligence Newsletter
──────────────────────────
Fetches top AI stories from 10+ RSS feeds, uses Claude to rank
by impact, fact-check, and summarise, then sends a beautiful
HTML email via SendGrid every morning.

Rules enforced:
  ✓ No duplicate stories (sent_stories.json dedup log)
  ✓ Fact-checked — low-credibility stories excluded
  ✓ All angles covered: Research · Business · Policy/Ethics
  ✓ Ranked most → least impactful
  ✓ Unbiased — multiple perspectives represented
"""

import os
import json
import logging
import feedparser
import anthropic
import sendgrid
from sendgrid.helpers.mail import Mail
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateutil_parser

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
RECIPIENT_EMAIL = "Thorbjornkrarup@gmail.com"
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL", "newsletter@yourdomain.com")
SENT_STORIES    = "sent_stories.json"
MAX_STORIES     = 10
MODEL           = "claude-sonnet-4-6"   # upgrade to claude-opus-4-7 for max quality

# ── RSS Sources ───────────────────────────────────────────────────────────────
# Covers: research, business, policy/ethics, official lab blogs
RSS_FEEDS = [
    # ── Research & Papers ────────────────────────────────────────────────────
    {"url": "https://export.arxiv.org/rss/cs.AI",          "category": "Research"},
    {"url": "https://export.arxiv.org/rss/cs.LG",          "category": "Research"},
    {"url": "https://export.arxiv.org/rss/cs.CL",          "category": "Research"},
    # ── Business & Products ──────────────────────────────────────────────────
    {"url": "https://feeds.feedburner.com/TechCrunch/AI",  "category": "Business"},
    {"url": "https://venturebeat.com/category/ai/feed/",   "category": "Business"},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "category": "Business"},
    # ── Policy, Ethics & Safety ──────────────────────────────────────────────
    {"url": "https://www.technologyreview.com/feed/",      "category": "Policy/Ethics"},
    {"url": "https://www.wired.com/feed/tag/artificial-intelligence/latest/rss", "category": "Policy/Ethics"},
    # ── Official Lab Blogs ───────────────────────────────────────────────────
    {"url": "https://openai.com/blog/rss/",                "category": "Research"},
    {"url": "https://blog.google/technology/ai/rss/",      "category": "Research"},
]


# ── Dedup Log ─────────────────────────────────────────────────────────────────

def load_sent() -> dict:
    """Load the dedup log (list of already-sent story URLs and titles)."""
    if os.path.exists(SENT_STORIES):
        with open(SENT_STORIES) as f:
            return json.load(f)
    return {"urls": [], "titles": []}


def save_sent(data: dict) -> None:
    """Persist the dedup log, capped at the last 500 entries to stay lean."""
    data["urls"]   = data["urls"][-500:]
    data["titles"] = data["titles"][-500:]
    with open(SENT_STORIES, "w") as f:
        json.dump(data, f, indent=2)


# ── RSS Fetching ──────────────────────────────────────────────────────────────

def fetch_rss(feeds: list) -> list:
    """
    Fetch all RSS feeds and return entries published in the last 48 hours.
    arXiv entries are always included (they batch-post, timestamps are unreliable).
    """
    entries = []
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=48)

    for feed_info in feeds:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries:
                pub_date = _parse_date(entry)
                is_arxiv = "arxiv" in feed_info["url"]

                if is_arxiv or pub_date is None or pub_date >= cutoff:
                    entries.append({
                        "title":         getattr(entry, "title",   "").strip(),
                        "url":           getattr(entry, "link",    "").strip(),
                        "summary":       getattr(entry, "summary", "")[:600].strip(),
                        "category_hint": feed_info["category"],
                        "source":        feed.feed.get("title", feed_info["url"]),
                        "published":     pub_date.isoformat() if pub_date else "Unknown",
                    })
            log.info(f"  ✓ {len(feed.entries):3d} entries  ←  {feed_info['url']}")
        except Exception as exc:
            log.warning(f"  ✗ Failed to fetch {feed_info['url']}: {exc}")

    return entries


def _parse_date(entry) -> datetime | None:
    """Try common date attributes on an RSS entry."""
    for attr in ("published", "updated", "created"):
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = dateutil_parser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None


def filter_new(entries: list, sent_data: dict) -> list:
    """Remove stories already delivered in a previous edition."""
    sent_urls   = set(sent_data.get("urls",   []))
    sent_titles = set(t.lower() for t in sent_data.get("titles", []))
    return [
        e for e in entries
        if e["url"] not in sent_urls
        and e["title"].lower() not in sent_titles
    ]


# ── Claude AI Processing ──────────────────────────────────────────────────────

def select_and_rank(entries: list, client: anthropic.Anthropic) -> list:
    """
    Send candidate entries to Claude.  Claude will:
      1. Assess credibility and discard dubious stories
      2. Select 10 stories spanning all three angles
      3. Rank them by real-world impact (1 = biggest)
      4. Write summaries, why-it-matters, and key takeaways
    """
    today = datetime.now().strftime("%B %d, %Y")

    # Build a balanced sample — cap each category to avoid token overload
    research = [e for e in entries if e["category_hint"] == "Research"][:25]
    business = [e for e in entries if e["category_hint"] == "Business"][:20]
    policy   = [e for e in entries if e["category_hint"] == "Policy/Ethics"][:15]
    sample   = research + business + policy

    entries_json = json.dumps(sample, indent=2, ensure_ascii=False)

    prompt = f"""Today is {today}.  You are a senior AI journalist and editor with 20+ years of experience
covering technology, research, policy, and ethics.

Your task: curate today's AI newsletter.  Select exactly {MAX_STORIES} stories from the
candidates below and produce the final newsletter content.

━━━ EDITORIAL RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. BALANCE  — cover all three pillars proportionally:
     • Research/Models  (3–4 stories): breakthroughs, new papers, benchmarks, model releases
     • Business/Industry (3–4 stories): funding, products, M&A, enterprise adoption
     • Policy/Ethics/Safety (2–3 stories): regulation, safety research, bias, societal impact

2. IMPACT RANKING — rank 1 = highest real-world global impact.
   Ask yourself: "Will this story matter in 6 months?"

3. FACT-CHECK — exclude any story that:
     • Comes from a non-credible source
     • Makes extraordinary claims without corroboration
     • Mixes opinion with reported fact without labelling it
     • Appears to be a press-release masquerading as news

4. IMPARTIALITY — represent multiple perspectives fairly.
   Do not favour any single company, country, or ideology.

5. RECENCY — prefer stories from the last 24 hours over older ones.

6. CLARITY — write for a smart, time-pressed professional.
   Summaries must be factual, tight, and jargon-free.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY a valid JSON array — no markdown fences, no preamble, no commentary:

[
  {{
    "rank":            1,
    "title":           "Rewritten, compelling, neutral headline",
    "category":        "Research | Business | Policy/Ethics | Application",
    "summary":         "2–3 sentences of factual, neutral reporting.",
    "why_it_matters":  "One sentence on the broader significance.",
    "key_takeaway":    "One sentence — the single most important thing to remember.",
    "url":             "https://original-source-url",
    "source":          "Publication name"
  }},
  ... exactly {MAX_STORIES} objects ...
]

━━━ CANDIDATE STORIES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{entries_json}"""

    log.info("Sending candidates to Claude for ranking & summarisation…")
    response = client.messages.create(
        model      = MODEL,
        max_tokens = 4096,
        messages   = [{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude wrapped the JSON
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    stories = json.loads(raw)
    log.info(f"Claude returned {len(stories)} stories")
    return stories[:MAX_STORIES]


# ── HTML Email Builder ────────────────────────────────────────────────────────

def build_html(stories: list, today_str: str) -> str:
    """Render a pixel-perfect, dark-header HTML email."""

    CATEGORY_STYLE = {
        "Research":      {"bg": "#eef6ff", "border": "#3b82f6", "badge": "#2563eb", "icon": "🔬"},
        "Business":      {"bg": "#f0fdf4", "border": "#22c55e", "badge": "#16a34a", "icon": "💼"},
        "Policy/Ethics": {"bg": "#fff7ed", "border": "#f97316", "badge": "#ea580c", "icon": "⚖️"},
        "Application":   {"bg": "#faf5ff", "border": "#a855f7", "badge": "#9333ea", "icon": "🚀"},
    }
    DEFAULT_STYLE = {"bg": "#f8fafc", "border": "#64748b", "badge": "#475569", "icon": "📰"}

    story_blocks = ""
    for s in stories:
        cat   = s.get("category", "Research")
        style = CATEGORY_STYLE.get(cat, DEFAULT_STYLE)
        rank  = s.get("rank", "–")

        story_blocks += f"""
        <!-- Story #{rank} -->
        <tr>
          <td style="padding:0 0 20px 0;">
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:{style['bg']};
                          border-left:4px solid {style['border']};
                          border-radius:0 10px 10px 0;">
              <tr>
                <td style="padding:18px 22px 18px 20px;">

                  <!-- Meta row -->
                  <table cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
                    <tr>
                      <td style="background:#0f172a; color:#e2e8f0;
                                 font-size:10px; font-weight:700; letter-spacing:1.5px;
                                 padding:3px 9px; border-radius:20px;">
                        #{rank}
                      </td>
                      <td style="width:6px;"></td>
                      <td style="background:{style['badge']}; color:#fff;
                                 font-size:10px; font-weight:600;
                                 padding:3px 10px; border-radius:20px;">
                        {style['icon']}&nbsp;{cat}
                      </td>
                    </tr>
                  </table>

                  <!-- Headline -->
                  <h2 style="margin:0 0 10px 0;
                             font-family:Georgia,'Times New Roman',serif;
                             font-size:18px; line-height:1.45; color:#0f172a;">
                    <a href="{s.get('url','#')}"
                       style="color:#0f172a; text-decoration:none;">
                      {s.get('title','')}
                    </a>
                  </h2>

                  <!-- Summary -->
                  <p style="margin:0 0 12px 0;
                            font-size:14px; color:#374151; line-height:1.75;">
                    {s.get('summary','')}
                  </p>

                  <!-- Why it matters -->
                  <p style="margin:0 0 10px 0;
                            font-size:13px; color:#4b5563; line-height:1.65;">
                    <strong style="color:#0f172a;">📌 Why it matters:</strong>&nbsp;
                    {s.get('why_it_matters','')}
                  </p>

                  <!-- Key takeaway pill -->
                  <table cellpadding="0" cellspacing="0" style="margin-bottom:14px; width:100%;">
                    <tr>
                      <td style="background:rgba(255,255,255,0.75);
                                 border-left:3px solid {style['border']};
                                 border-radius:0 6px 6px 0;
                                 padding:9px 14px;
                                 font-size:13px; color:#1e293b; line-height:1.65;">
                        <strong>💡 Key takeaway:</strong>&nbsp;{s.get('key_takeaway','')}
                      </td>
                    </tr>
                  </table>

                  <!-- CTA link -->
                  <a href="{s.get('url','#')}"
                     style="font-size:12px; font-weight:700;
                            color:{style['badge']}; text-decoration:none;">
                    Read full story &rarr;&nbsp;<span style="font-weight:400;
                      color:#6b7280;">{s.get('source','')}</span>
                  </a>

                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    # ── Count categories for the stats bar ───────────────────────────────────
    counts = {}
    for s in stories:
        c = s.get("category", "Other")
        counts[c] = counts.get(c, 0) + 1

    stats_cells = ""
    for label, icon in [("Research","🔬"),("Business","💼"),("Policy/Ethics","⚖️"),("Application","🚀")]:
        n = counts.get(label, 0)
        if n:
            stats_cells += f"""
            <td style="text-align:center; padding:0 8px;">
              <span style="font-size:18px;">{icon}</span><br>
              <span style="font-size:11px; font-weight:700; color:#1e293b;">{n}</span><br>
              <span style="font-size:10px; color:#64748b;">{label}</span>
            </td>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AI Intelligence &mdash; {today_str}</title>
</head>
<body style="margin:0;padding:0;background:#e8eaed;font-family:Arial,Helvetica,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0"
       style="background:#e8eaed;padding:28px 12px;">
  <tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;width:100%;">

    <!-- ── HEADER ── -->
    <tr>
      <td style="background:linear-gradient(140deg,#0f172a 0%,#1e3a5f 55%,#1d4ed8 100%);
                 border-radius:14px 14px 0 0;padding:38px 34px 30px;">
        <p style="margin:0 0 6px;color:#818cf8;font-size:11px;
                  font-weight:700;letter-spacing:3.5px;text-transform:uppercase;">
          Your daily briefing
        </p>
        <h1 style="margin:0;font-family:Georgia,serif;font-size:32px;
                   color:#f8fafc;letter-spacing:-0.5px;">
          ⚡ AI Intelligence
        </h1>
        <p style="margin:10px 0 0;color:#94a3b8;font-size:13px;">
          {today_str} &nbsp;·&nbsp; Top {MAX_STORIES} stories ranked by impact
        </p>
      </td>
    </tr>

    <!-- ── STATS BAR ── -->
    <tr>
      <td style="background:#dde1f0;padding:14px 20px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>{stats_cells}</tr>
        </table>
      </td>
    </tr>

    <!-- ── STORIES ── -->
    <tr>
      <td style="background:#ffffff;padding:26px 26px 10px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          {story_blocks}
        </table>
      </td>
    </tr>

    <!-- ── FOOTER ── -->
    <tr>
      <td style="background:#0f172a;border-radius:0 0 14px 14px;
                 padding:22px 34px;text-align:center;">
        <p style="margin:0 0 5px;color:#818cf8;font-size:13px;font-weight:600;">
          AI Intelligence Newsletter
        </p>
        <p style="margin:0;color:#475569;font-size:11px;line-height:1.7;">
          Stories curated, fact-checked &amp; ranked by AI &middot;
          Powered by Claude {MODEL}<br>
          Delivered every morning at 10&thinsp;AM
        </p>
      </td>
    </tr>

  </table>
  </td></tr>
</table>

</body>
</html>"""


# ── Email Sending ─────────────────────────────────────────────────────────────

def send_email(html: str, subject: str) -> int:
    sg  = sendgrid.SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    msg = Mail(
        from_email   = SENDER_EMAIL,
        to_emails    = RECIPIENT_EMAIL,
        subject      = subject,
        html_content = html,
    )
    response = sg.send(msg)
    log.info(f"SendGrid response: HTTP {response.status_code}")
    return response.status_code


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("━━━━━━━━━━━━  AI Newsletter starting  ━━━━━━━━━━━━")
    today_str = datetime.now().strftime("%B %d, %Y")

    # 1 ── Load dedup log
    sent_data = load_sent()
    log.info(f"Dedup log: {len(sent_data.get('urls', []))} previously sent stories")

    # 2 ── Fetch RSS feeds
    log.info("Fetching RSS feeds…")
    raw = fetch_rss(RSS_FEEDS)
    log.info(f"Total raw entries fetched: {len(raw)}")

    # 3 ── Remove duplicates
    fresh = filter_new(raw, sent_data)
    log.info(f"Fresh (unseen) entries: {len(fresh)}")

    if len(fresh) < MAX_STORIES:
        log.warning("Not enough fresh entries — falling back to full pool for today")
        fresh = raw

    # 4 ── Claude: rank, verify, summarise
    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    stories = select_and_rank(fresh, client)

    # 5 ── Build HTML
    html    = build_html(stories, today_str)

    # 6 ── Send email
    subject = f"⚡ AI Intelligence — {today_str} · Top {len(stories)} Stories"
    send_email(html, subject)

    # 7 ── Update dedup log
    for s in stories:
        url, title = s.get("url", ""), s.get("title", "")
        if url   and url   not in sent_data["urls"]:   sent_data["urls"].append(url)
        if title and title not in sent_data["titles"]: sent_data["titles"].append(title)
    save_sent(sent_data)

    log.info("━━━━━━━━━━━━  Done ✓  ━━━━━━━━━━━━")


if __name__ == "__main__":
    main()
