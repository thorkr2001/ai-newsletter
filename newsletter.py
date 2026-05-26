#!/usr/bin/env python3
"""
AI Intelligence Newsletter
──────────────────────────
Uses Claude with web search to find & rank today's top 10 AI stories,
then sends a beautiful HTML email via SendGrid.
"""

import os
import json
import logging
import anthropic
import sendgrid
from sendgrid.helpers.mail import Mail
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
RECIPIENT_EMAIL = "Thorbjornkrarup@gmail.com"
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL", "Thorbjornkrarup@gmail.com")
SENT_STORIES    = "sent_stories.json"
MAX_STORIES     = 10
MODEL           = "claude-sonnet-4-6"

# ── Dedup Log ─────────────────────────────────────────────────────────────────

def load_sent() -> dict:
    if os.path.exists(SENT_STORIES):
        with open(SENT_STORIES) as f:
            return json.load(f)
    return {"urls": [], "titles": []}

def save_sent(data: dict) -> None:
    data["urls"]   = data["urls"][-500:]
    data["titles"] = data["titles"][-500:]
    with open(SENT_STORIES, "w") as f:
        json.dump(data, f, indent=2)

# ── Claude Web Search ─────────────────────────────────────────────────────────

def fetch_and_rank_stories(client: anthropic.Anthropic, sent_data: dict) -> list:
    """Use Claude with web search to find, fact-check and rank today's AI stories."""
    today    = datetime.now().strftime("%B %d, %Y")
    sent_str = json.dumps(sent_data.get("urls", [])[:100])

    prompt = f"""Today is {today}. You are a senior AI journalist and editor.

Search the web for today's most important AI news stories. Then select exactly {MAX_STORIES} stories for the daily newsletter.

PREVIOUSLY SENT URLs (do NOT include these):
{sent_str}

SEARCH STRATEGY — search across all three pillars:
1. AI Research/Models: new papers, model releases, benchmarks (search: "AI research {today}", "new AI model 2026", site:arxiv.org AI)
2. Business/Industry: funding, products, M&A (search: "AI startup funding", "AI product launch", "AI acquisition")
3. Policy/Ethics/Safety: regulation, safety, bias (search: "AI regulation", "AI safety", "AI ethics")

EDITORIAL RULES:
- Cover all 3 pillars proportionally: Research(3-4), Business(3-4), Policy/Ethics(2-3)
- Rank 1 = highest global real-world impact
- Exclude unverified, sensational, or press-release-only stories
- Be completely unbiased — represent all perspectives
- Only stories from the last 48 hours

Return ONLY a valid JSON array, no markdown, no commentary:

[
  {{
    "rank": 1,
    "title": "Compelling neutral headline",
    "category": "Research",
    "summary": "2-3 sentences of factual neutral reporting.",
    "why_it_matters": "One sentence on broader significance.",
    "key_takeaway": "Single most important thing to remember.",
    "url": "https://source-url",
    "source": "Publication name"
  }}
]

Search now, then return the JSON array of exactly {MAX_STORIES} stories."""

    messages = [{"role": "user", "content": prompt}]
    tools    = [{"type": "web_search_20250305", "name": "web_search"}]

    log.info("Searching for today's AI stories via Claude web search…")

    for iteration in range(15):
        response = client.messages.create(
            model      = MODEL,
            max_tokens = 8000,
            tools      = tools,
            messages   = messages,
        )

        log.info(f"  Iteration {iteration+1}: stop_reason={response.stop_reason}, blocks={[b.type for b in response.content]}")

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text") and block.text.strip().startswith("["):
                    raw = block.text.strip()
                    if raw.startswith("```"):
                        raw = raw.split("```")[1].lstrip("json").strip()
                    stories = json.loads(raw)
                    log.info(f"Got {len(stories)} stories from Claude")
                    return stories[:MAX_STORIES]
            # Text didn't start with [ — grab any text and try
            for block in response.content:
                if hasattr(block, "text"):
                    raw = block.text.strip()
                    start = raw.find("[")
                    end   = raw.rfind("]")
                    if start != -1 and end != -1:
                        stories = json.loads(raw[start:end+1])
                        log.info(f"Got {len(stories)} stories (extracted JSON)")
                        return stories[:MAX_STORIES]
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": ""}
                for b in response.content if b.type == "tool_use"
            ]
            if tool_results:
                messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Claude did not return a valid JSON story list")

# ── HTML Builder ──────────────────────────────────────────────────────────────

def build_html(stories: list, today_str: str) -> str:
    CAT = {
        "Research":      {"bg":"#eef6ff","border":"#3b82f6","badge":"#2563eb","icon":"🔬"},
        "Business":      {"bg":"#f0fdf4","border":"#22c55e","badge":"#16a34a","icon":"💼"},
        "Policy/Ethics": {"bg":"#fff7ed","border":"#f97316","badge":"#ea580c","icon":"⚖️"},
        "Application":   {"bg":"#faf5ff","border":"#a855f7","badge":"#9333ea","icon":"🚀"},
    }
    DEFAULT = {"bg":"#f8fafc","border":"#64748b","badge":"#475569","icon":"📰"}

    blocks = ""
    for s in stories:
        c = CAT.get(s.get("category",""), DEFAULT)
        blocks += f"""
        <tr><td style="padding:0 0 18px 0;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:{c['bg']};border-left:4px solid {c['border']};border-radius:0 10px 10px 0;">
            <tr><td style="padding:18px 22px 18px 20px;">
              <table cellpadding="0" cellspacing="0" style="margin-bottom:10px;"><tr>
                <td style="background:#0f172a;color:#e2e8f0;font-size:10px;font-weight:700;letter-spacing:1.5px;padding:3px 9px;border-radius:20px;">#{s.get('rank','')}</td>
                <td style="width:6px;"></td>
                <td style="background:{c['badge']};color:#fff;font-size:10px;font-weight:600;padding:3px 10px;border-radius:20px;">{c['icon']}&nbsp;{s.get('category','')}</td>
              </tr></table>
              <h2 style="margin:0 0 10px;font-family:Georgia,serif;font-size:18px;line-height:1.45;color:#0f172a;">
                <a href="{s.get('url','#')}" style="color:#0f172a;text-decoration:none;">{s.get('title','')}</a>
              </h2>
              <p style="margin:0 0 12px;font-size:14px;color:#374151;line-height:1.75;">{s.get('summary','')}</p>
              <p style="margin:0 0 10px;font-size:13px;color:#4b5563;line-height:1.65;">
                <strong style="color:#0f172a;">📌 Why it matters:</strong>&nbsp;{s.get('why_it_matters','')}
              </p>
              <table cellpadding="0" cellspacing="0" style="margin-bottom:14px;width:100%;"><tr>
                <td style="background:rgba(255,255,255,0.75);border-left:3px solid {c['border']};border-radius:0 6px 6px 0;padding:9px 14px;font-size:13px;color:#1e293b;line-height:1.65;">
                  <strong>💡 Key takeaway:</strong>&nbsp;{s.get('key_takeaway','')}
                </td>
              </tr></table>
              <a href="{s.get('url','#')}" style="font-size:12px;font-weight:700;color:{c['badge']};text-decoration:none;">
                Read full story &rarr;&nbsp;<span style="font-weight:400;color:#6b7280;">{s.get('source','')}</span>
              </a>
            </td></tr>
          </table>
        </td></tr>"""

    counts = {}
    for s in stories:
        k = s.get("category","Other")
        counts[k] = counts.get(k,0)+1

    stats = ""
    for label,icon in [("Research","🔬"),("Business","💼"),("Policy/Ethics","⚖️"),("Application","🚀")]:
        if counts.get(label):
            stats += f'<td style="text-align:center;padding:0 8px;"><span style="font-size:18px;">{icon}</span><br><span style="font-size:11px;font-weight:700;color:#1e293b;">{counts[label]}</span><br><span style="font-size:10px;color:#64748b;">{label}</span></td>'

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Intelligence — {today_str}</title></head>
<body style="margin:0;padding:0;background:#e8eaed;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#e8eaed;padding:28px 12px;">
<tr><td align="center"><table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
  <tr><td style="background:linear-gradient(140deg,#0f172a 0%,#1e3a5f 55%,#1d4ed8 100%);border-radius:14px 14px 0 0;padding:38px 34px 30px;">
    <p style="margin:0 0 6px;color:#818cf8;font-size:11px;font-weight:700;letter-spacing:3.5px;text-transform:uppercase;">Your daily briefing</p>
    <h1 style="margin:0;font-family:Georgia,serif;font-size:32px;color:#f8fafc;letter-spacing:-0.5px;">⚡ AI Intelligence</h1>
    <p style="margin:10px 0 0;color:#94a3b8;font-size:13px;">{today_str} &nbsp;·&nbsp; Top {MAX_STORIES} stories ranked by impact</p>
  </td></tr>
  <tr><td style="background:#dde1f0;padding:14px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>{stats}</tr></table>
  </td></tr>
  <tr><td style="background:#ffffff;padding:26px 26px 10px;">
    <table width="100%" cellpadding="0" cellspacing="0">{blocks}</table>
  </td></tr>
  <tr><td style="background:#0f172a;border-radius:0 0 14px 14px;padding:22px 34px;text-align:center;">
    <p style="margin:0 0 5px;color:#818cf8;font-size:13px;font-weight:600;">AI Intelligence Newsletter</p>
    <p style="margin:0;color:#475569;font-size:11px;line-height:1.7;">
      Stories curated, fact-checked &amp; ranked by Claude AI<br>Delivered every morning at 10 AM
    </p>
  </td></tr>
</table></td></tr></table></body></html>"""

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(html: str, subject: str) -> int:
    sg  = sendgrid.SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    msg = Mail(from_email=SENDER_EMAIL, to_emails=RECIPIENT_EMAIL,
               subject=subject, html_content=html)
    r = sg.send(msg)
    log.info(f"SendGrid: HTTP {r.status_code}")
    return r.status_code

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("━━━━━━━━  AI Newsletter starting  ━━━━━━━━")
    today_str = datetime.now().strftime("%B %d, %Y")
    sent_data = load_sent()
    log.info(f"Dedup log: {len(sent_data.get('urls',[]))} previously sent stories")

    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    stories = fetch_and_rank_stories(client, sent_data)

    html    = build_html(stories, today_str)
    subject = f"⚡ AI Intelligence — {today_str} · Top {len(stories)} Stories"
    send_email(html, subject)

    for s in stories:
        url, title = s.get("url",""), s.get("title","")
        if url   and url   not in sent_data["urls"]:   sent_data["urls"].append(url)
        if title and title not in sent_data["titles"]: sent_data["titles"].append(title)
    save_sent(sent_data)
    log.info("━━━━━━━━  Done ✓  ━━━━━━━━")

if __name__ == "__main__":
    main()
