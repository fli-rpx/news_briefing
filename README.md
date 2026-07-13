# Morning Briefing

Daily news briefing with Observer Commentary. Tracks both NYT and WSJ briefings with PDF and Web version support.

## Files

- `index.html` — Main page with today's links (NYT + WSJ) and three observer analysis sections
- `archive.html` — Browse past briefings with PDF + Web links per source
- `style.css` — Dark-themed styles for the briefing layout
- `serve.py` — Custom HTTP server (mounts external PDF directory under `/reports/`)
- `data/reports_index.json` — JSON index of all briefings by date and source
- `scripts/update_index.py` — CLI tool to add/update entries in the reports index
- `scripts/build_combined.py` — Builds a combined NYT + WSJ HTML page from latest source files
- `README.md` — Project documentation

## Observer Analysis Sections

1. **翟东升 (Zhai Dongsheng)** — Sovereign credit, people-centered political economy
2. **金灿荣 (Jin Canrong)** — Unprecedented changes, strategic analysis with humor
3. **宋鸿兵 (Song Hongbing)** — Dollar circulation, financial sovereignty

## Usage

### Serve locally

```bash
cd ~/Projects/MorningBriefing && python3 serve.py 8080
```

Then visit http://localhost:8080

> **Note:** Use `serve.py` instead of `python3 -m http.server` because `serve.py` also mounts the external PDF directory (`/Users/fudongli/.hermes/`) under `/reports/`, making the PDF files accessible to the browser.

### Add a briefing entry

```bash
python3 scripts/update_index.py --source nyt --date 2026-06-04 \
    --pdf nyt_briefing_2026-06-04.pdf --web https://xxx.kimi.page
```

### Build combined HTML

```bash
python3 scripts/build_combined.py --input-dir /Users/fudongli/.hermes \
    --output /Users/fudongli/.hermes/combined_latest.html
```
