# Planet Briefing

A world news digest that builds itself. Every 30 minutes it:

1. reads ~40 public news feeds from every continent,
2. merges reports of the same story from different outlets,
3. asks Claude (`claude-haiku-5-5`) to sort each story by region and topic and write 2–4 neutral bullet points,
4. picks the 10 most significant stories of the day,
5. publishes a fast, simple website on GitHub Pages, and saves each day to a 90-day archive.

Stories already summarised earlier in the day are reused, so updating every 30 minutes costs about the same as updating once a day.

Once it's set up you don't need to do anything. With Claude a run costs about **1–2 US cents**.

**No API key yet? It still works.** With the default `summariser: "auto"` setting in `config.yaml`, the site uses a **free mode** whenever the key is missing or doesn't work: stories are sorted by keyword rules, and each one shows the short summary its outlet publishes. As soon as a working key is saved as a GitHub secret, the next run switches to Claude's bullet points by itself.

---

## What's in this folder

| Path | What it is |
|---|---|
| `feeds.yaml` | **The list of news sources.** Edit this to add or remove outlets. |
| `config.yaml` | **Settings:** site name, number of stories, archive length, categories. |
| `run_local.py` | Runs the whole pipeline on your computer. |
| `pipeline/` | The Python code (fetching, merging, summarising, building pages). |
| `templates/`, `static/style.css` | The look of the website. |
| `data/archive/` | One small file per day. The archive pages are built from these. |
| `tests/` | Automatic checks that run before every deploy. |
| `.github/workflows/daily.yml` | The daily automation on GitHub. |

---

## Step 1 — Test it on your computer

You'll use the **Terminal** app (press ⌘ + Space, type *Terminal*, press Enter).

**1a. Go to this folder.** Type `cd ` (with a space after it), drag this folder from Finder into the Terminal window, and press Enter.

**1b. Install the requirements (one time only):**

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

**1c. Run the tests:**

```bash
.venv/bin/python -m pytest
```

You should see something like `15 passed`.

**1d. Do a free practice run.** This fetches real news and builds the site in free mode (no Claude, costs nothing, nothing saved to the archive):

```bash
.venv/bin/python run_local.py --dry-run
```

Then open the site:

```bash
open _site/index.html
```

**1e. Do a real run with Claude.** First give the pipeline your API key. Create a file named `.env` in this folder containing one line:

```
ANTHROPIC_API_KEY=sk-ant-...your key...
```

(You can make it with `nano .env`: paste the line, then press Ctrl+O, Enter, Ctrl+X.) The `.env` file is listed in `.gitignore`, so it is **never** uploaded to GitHub.

Then run:

```bash
.venv/bin/python run_local.py
```

At the end it prints the tokens used and the cost. Open `_site/index.html` again to see the real summaries.

> A real run also saves today's file in `data/archive/`. That's fine: it becomes the first day of your archive.

---

## Step 2 — Create a GitHub account and repository

1. Go to <https://github.com/signup> and create a free account.
2. Install **GitHub Desktop** from <https://desktop.github.com> and sign in with that account.
   This is the easiest way to upload the code, and it handles logging in for you.
3. In GitHub Desktop choose **File → Add Local Repository…** and pick this folder.
   It will say this isn't a Git repository yet. Click **create a repository**, keep the name `planet-briefing`, and click **Create Repository**.
4. Click **Publish repository**.
   - **Untick "Keep this code private".** GitHub Pages is free only for public repositories. Your API key is not in the code, so this is safe.
   - Click **Publish Repository**.

Your code is now at `https://github.com/YOUR-USERNAME/planet-briefing`.

---

## Step 3 — Add your API key as a GitHub secret (optional, for AI summaries)

Skip this step if you don't have a working key yet. The site runs in free mode until you add one.

The daily run needs your Anthropic key. GitHub stores it encrypted, and it's never shown in logs.

1. On your **repository** page (not your profile), click **Settings** in the top bar. If you don't see it, your window is too narrow: click the **⋯** at the end of that bar.
2. In the left menu, scroll down to the **Security** heading, click **Secrets and variables** to open it, then click **Actions**.
   Shortcut: go straight to `https://github.com/YOUR-USERNAME/planet-briefing/settings/secrets/actions`.
3. Click **New repository secret**.
4. Name: `ANTHROPIC_API_KEY` (exactly like that). Secret: paste your key.
5. Click **Add secret**.

---

## Step 4 — Turn on GitHub Pages

1. Still in **Settings**, click **Pages** in the left menu.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.

That's all. There's nothing else to select.

---

## Step 5 — Run it for the first time

1. Click the **Actions** tab at the top of your repository.
2. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
3. Click **Daily briefing** on the left, then **Run workflow → Run workflow**.
4. Wait 2–4 minutes. A green tick means it worked.
5. Your site is live at **`https://YOUR-USERNAME.github.io/planet-briefing/`**
   (the link is also shown on the finished run under *deploy*, and in Settings → Pages).

From now on it runs by itself every 30 minutes. GitHub sometimes starts scheduled runs late, or skips one when it's very busy, which is normal.

---

## Your web address

The site lives at **https://planetbriefing.org** (registered at Cloudflare; renew it there each year, or turn on auto-renew).
Its DNS records in Cloudflare point to GitHub Pages and are **Proxied** (orange cloud), so Cloudflare counts every visit.
Keep Cloudflare's **SSL/TLS → encryption mode on "Full"** (not "Flexible", which causes a redirect loop, and not "Full (strict)", which breaks when GitHub's own certificate expires).

**Visitor numbers** are in two places in Cloudflare:
- **Analytics → Web analytics → planetbriefing.org**: real people (visits, top pages, countries, devices). Misses visitors using ad blockers.
- **planetbriefing.org → Analytics** (the domain's own page): every request that reached the site, including people with ad blockers, plus some bots.
The old `hadssm52.github.io/planet-briefing` link redirects to it automatically.
If you ever change the address, update `url:` in `config.yaml` and the custom domain in **Settings → Pages**.

## Changing the news sources

Open `feeds.yaml` (on GitHub: click the file, then the ✏️ pencil icon). Each source looks like this:

```yaml
  - name: "Al Jazeera"
    url: "https://www.aljazeera.com/xml/rss/all.xml"
```

- **Add a source:** copy a block, then change the name and the RSS feed address. Most news sites list their feeds on a page called "RSS".
- **Remove a source:** delete its block, or add `enabled: false` under it.
- Save with **Commit changes**. The next run uses the new list.

If a feed stops working, the run just skips it and lists it under "Skipped feeds" in the log.

## Changing settings

Edit `config.yaml`:

- `archive_days: 90` sets how many days of archive to keep.
- `max_stories: 150` sets how many stories a day. More stories means a slightly higher cost.
- `site: title:` sets the site name.
- `regions:` / `topics:` set the categories. If you rename one, keep the `slug` simple (lowercase, no spaces).

To change how often it runs, edit the `cron: "*/30 * * * *"` line in `.github/workflows/daily.yml`. For example `"0 * * * *"` is every hour and `"0 6 * * *"` is once a day at 06:00 UTC.

---

## If something breaks

**You'll get an email** from GitHub when a run fails. When that happens, **yesterday's site stays online**: nothing is published unless every step succeeds.

To see what went wrong:

1. Go to the **Actions** tab and click the failed run (red ✗).
2. Click the **build** job, then the step with the red ✗ to expand its log.
3. Look near the bottom for a line starting with `RUN FAILED:` or `Error`.

Common problems:

| Message | Fix |
|---|---|
| `ANTHROPIC_API_KEY is not set` | Only happens with `summariser: "claude"`. Add the secret (Step 3) or switch back to `"auto"`. |
| `Falling back to free mode for today` | Not an error: the key was missing or rejected, so the site used free mode. Check the key in the Anthropic Console and update the secret. |
| `authentication_error` / `401` | The key is wrong or was deleted. Make a new key at console.anthropic.com and update the secret. |
| `credit balance is too low` | Add credit in the Anthropic Console (Billing). |
| `only N stories summarised` | Most feeds or API calls failed. Usually temporary: press **Run workflow** to retry. |
| A test failed | Usually caused by an edit to `config.yaml` or `feeds.yaml` (for example a typo or bad indentation). Undo the last change. |
| *deploy* fails with "Pages not enabled" | Redo Step 4. |
| `Permission denied` when pushing | Settings → Actions → General → Workflow permissions → choose **Read and write permissions** → Save. |

The log of each successful run also shows which feeds were skipped, and the token usage and cost.

---

## Good to know

- **Free mode** sorts stories by keyword lists in `pipeline/classify.py`. It is good but not perfect; add words there if stories land in the wrong place.
- **Costs:** in Claude mode the run prints an estimate before calling Claude and the actual figure after. With ~150 stories a day it's around $0.01–0.02 per run, or under $1 a month. Prices are set in `config.yaml` in case they change.
- **What's used from each outlet:** only the headline, the short description and the link from its public feed. Articles are never downloaded. Claude writes the bullets in its own words, and the code also rejects any bullet that repeats 8 or more words in a row from the source.
- **Wire services:** Reuters and AP no longer offer public RSS feeds, and AFP has no public English feed, so they can't be listed directly. Their reporting reaches the digest through outlets such as France 24 and Anadolu that carry wire copy in their own feeds.
- **NHK World** is in `feeds.yaml` but switched off, because it doesn't currently publish a working English feed.
- **Stays active:** GitHub pauses scheduled workflows in repositories with no activity for 60 days. The daily archive commit counts as activity, so this won't happen while runs succeed.
- **Privacy:** no cookies, no login. Visits are counted anonymously with Cloudflare Web Analytics (see them at dash.cloudflare.com → Analytics → Web analytics; set `cloudflare_analytics_token: ""` in `config.yaml` to turn it off). Story photos load straight from the news outlets' own servers; set `show_images: false` for a text-only site.
- **Other commands:**
  - `.venv/bin/python run_local.py --rebuild` rebuilds the pages from saved days without fetching anything.
  - `.venv/bin/python -m http.server --directory _site 8000` lets you view the site at <http://localhost:8000> exactly as it will look online.
