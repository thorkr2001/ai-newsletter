# ⚡ AI Intelligence Newsletter

Automated daily newsletter delivering the **top 10 AI stories, ranked by real-world impact**, to your inbox every morning at 10 AM.

Powered by **Claude AI** + **SendGrid** + **GitHub Actions** — ~$1/month, zero servers.

---

## What it does

| Step | Detail |
|------|--------|
| 🔍 **Scans** | 10+ RSS feeds from arXiv, TechCrunch, VentureBeat, MIT Tech Review, Wired, The Verge, OpenAI blog, Google AI blog |
| 🤖 **Ranks** | Claude evaluates every story and ranks 1–10 by global impact |
| ✅ **Fact-checks** | Low-credibility or unverified stories are excluded automatically |
| 📐 **Balances** | Always covers Research · Business · Policy/Ethics proportionally |
| 🚫 **Deduplicates** | `sent_stories.json` ensures no story is ever sent twice |
| 📧 **Delivers** | Beautiful HTML email via SendGrid every morning |

---

## Setup (~10 minutes)

### Step 1 — Fork / clone this repo

```bash
git clone https://github.com/YOUR_USERNAME/ai-newsletter.git
cd ai-newsletter
```

Push it to your own GitHub account (public or private — both work).

---

### Step 2 — Get your API keys

#### Anthropic (Claude)
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. **API Keys** → **Create Key**
3. Copy the `sk-ant-...` key

> 💰 Cost: Claude Sonnet 4.6 costs ~$3 per million input tokens.  
> Each newsletter run uses ~6,000 tokens = **~$0.02 per day = ~$0.60/month**

#### SendGrid (email delivery)
1. Create a free account at [app.sendgrid.com](https://app.sendgrid.com)
2. **Settings → API Keys → Create API Key** (choose "Full Access")
3. Copy the `SG.xxx...` key
4. **Settings → Sender Authentication** → verify the email address you'll send *from*

> 💰 Cost: Free tier = 100 emails/day forever. More than enough.

---

### Step 3 — Add GitHub Secrets

Go to your repo on GitHub:  
**Settings → Secrets and variables → Actions → New repository secret**

Add these three secrets:

| Secret name | Value | Example |
|-------------|-------|---------|
| `ANTHROPIC_API_KEY` | Your Claude API key | `sk-ant-api03-...` |
| `SENDGRID_API_KEY` | Your SendGrid API key | `SG.xxxxxxxx...` |
| `SENDER_EMAIL` | The email you verified in SendGrid | `you@yourdomain.com` |

---

### Step 4 — Enable GitHub Actions

1. Go to the **Actions** tab in your repo
2. If prompted, click **"I understand my workflows, go ahead and enable them"**

✅ That's it. The newsletter will run automatically at **08:00 UTC** every day.

---

## Manual send (test it now)

**Actions tab → ⚡ AI Intelligence Newsletter → Run workflow → Run workflow**

Check your inbox within ~60 seconds.

---

## Timezone

The cron schedule is set to `0 8 * * *` (UTC):

| Season | Your time (Copenhagen) | UTC |
|--------|----------------------|-----|
| Summer (CEST, Apr–Oct) | **10:00 AM** ✓ | 08:00 |
| Winter (CET, Oct–Apr) | 09:00 AM | 08:00 |

To keep it at 10 AM in winter too, change the cron to `0 9 * * *` in `.github/workflows/newsletter.yml`.

---

## File structure

```
ai-newsletter/
├── .github/
│   └── workflows/
│       └── newsletter.yml     ← GitHub Actions scheduler
├── newsletter.py              ← Main script (fetch → rank → send)
├── requirements.txt           ← Python dependencies
├── sent_stories.json          ← Dedup log (auto-updated by bot)
└── README.md
```

---

## Customisation

| What to change | Where |
|---------------|-------|
| Recipient email | `RECIPIENT_EMAIL` in `newsletter.py` |
| Number of stories | `MAX_STORIES` in `newsletter.py` |
| Claude model | `MODEL` in `newsletter.py` (try `claude-opus-4-7` for max quality) |
| RSS sources | `RSS_FEEDS` list in `newsletter.py` |
| Send time | `cron` in `.github/workflows/newsletter.yml` |
| Sender email | `SENDER_EMAIL` GitHub Secret |

### Adding RSS feeds

```python
RSS_FEEDS = [
    ...existing feeds...
    {"url": "https://your-new-feed.com/rss", "category": "Business"},
    # category options: "Research" | "Business" | "Policy/Ethics"
]
```

---

## Cost breakdown

| Item | Cost |
|------|------|
| Claude Sonnet 4.6 | ~$0.02/day |
| SendGrid | Free (100/day) |
| GitHub Actions | Free (2,000 min/month) |
| **Total** | **~$0.60/month** |

---

## Troubleshooting

**Newsletter not arriving?**
- Check the Actions tab for error logs
- Confirm your `SENDER_EMAIL` is verified in SendGrid
- Check your spam folder
- Run manually via Actions → Run workflow

**"Less than 10 fresh entries" warning?**
- Normal on slow news days — the script falls back to the full RSS pool

**Stories seem old?**
- arXiv posts in daily batches, so research papers may appear dated — this is expected

---

## How deduplication works

After every send, the script appends the URLs and titles of all 10 delivered stories to `sent_stories.json` and commits it back to the repo. On the next run, any story whose URL *or* title appears in that file is excluded from consideration.

The log is capped at the last 500 entries to stay lean (~40 KB).

---

*Built with Claude AI · Delivered by SendGrid · Scheduled by GitHub Actions*
