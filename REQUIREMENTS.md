# Morning Briefing — Combined NYT + WSJ Upgrade

## Goal
Upgrade the MorningBriefing project to track both NYT and WSJ briefings with PDF + Kimi Web page URLs, display combined content, and publish to GitHub.

## Changes Required

### 1. Create `data/reports_index.json`
A JSON index file storing per-date entries for both sources.

Schema:
```json
{
  "2026-06-04": {
    "nyt": {
      "pdf": "nyt_briefing_2026-06-04.pdf",
      "web": "https://xxx.kimi.page"
    },
    "wsj": {
      "pdf": "wsj_briefing_2026-06-04.pdf",
      "web": "https://xxx.kimi.page"
    }
  }
}
```

This file lives in `data/reports_index.json` within the project directory.

### 2. Update `index.html`
- Add a **web version link** for today's briefing alongside the existing PDF link
- Show both NYT and WSJ links (not just one)
- The page already shows the combined observer analysis — keep that layout

### 3. Update `archive.html`
- Currently scans directory listing for PDF files only
- Add a second column showing **Web version link** when an entry exists in reports_index.json
- Show source label (NYT/WSJ) and date
- Sort newest first

### 4. Create `data/` directory structure
```
MorningBriefing/
├── data/
│   └── reports_index.json
├── index.html
├── archive.html
├── style.css
├── serve.py
├── README.md
└── REQUIREMENTS.md
```

### 5. Create `scripts/update_index.py`
A script that can be called by the NYT/WSJ pipeline after generating a briefing:
```bash
python3 scripts/update_index.py --source nyt --date 2026-06-04 --pdf nyt_briefing_2026-06-04.pdf --web https://xxx.kimi.page
```

Updates `data/reports_index.json` with the new entry.

### 6. Create `scripts/build_combined.py`
A script that reads the latest NYT + WSJ observer analysis files and generates a combined HTML page that:
- Merges both briefings into a single beautiful dark-themed HTML page
- Shows both source labels
- Can be uploaded to Kimi Websites or saved as a static HTML
- (Future use — not blocking the GitHub push)

### 7. Push to GitHub
Push the entire `MorningBriefing/` directory to `https://github.com/fli-rpx/news_briefing`.

## Implementation Order
1. Create `data/` directory + `data/reports_index.json` (empty array)
2. Update `archive.html` to read from the index and show both PDF + Web links
3. Update `index.html` to show both source links for today
4. Create `scripts/update_index.py`
5. Create `scripts/build_combined.py`
6. Push to GitHub

## Constraints
- Keep the existing dark theme and layout consistent
- No external dependencies beyond what's already used
- The serve.py must still serve everything correctly
- Telegram markdown: no tables, use bullet lists
