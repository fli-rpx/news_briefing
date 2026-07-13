#!/usr/bin/env python3
"""Generate a self-contained static HTML briefing from the June 12, 2026 NYT text."""

import html
import os
import re

SRC = "/tmp/nyt_full_text_2026-06-12.txt"
OUT = "/tmp/brf/briefings/nyt_2026-06-12.html"


def read_clean_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    # Remove form-feed characters and repeated header/page markers.
    text = text.replace("\f", "")
    text = re.sub(r"\n\s*NYT Master Briefing\s*\n", "\n", text)
    text = re.sub(r"\n\s*Page \d+/\d+\s*\n", "\n", text)
    # Collapse multiple blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def esc(s: str) -> str:
    return html.escape(s).strip()


def paragraphs(text: str) -> str:
    """Join lines within blank-line-separated blocks and wrap as HTML paragraphs."""
    blocks = re.split(r"\n\s*\n", text.strip())
    out = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        para = " ".join(lines)
        # Preserve inline bold markers if any.
        out.append(f"<p>{esc(para)}</p>")
    return "\n".join(out)


def bullets(text: str) -> str:
    """Wrap non-empty lines as <li>."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    items = "\n".join(f"<li>{esc(ln)}</li>" for ln in lines)
    return f"<ul>\n{items}\n</ul>"


def extract_between(text: str, start: str, end: str = None) -> str:
    i = text.find(start)
    if i == -1:
        return ""
    j = text.find(end, i + len(start)) if end else len(text)
    if j == -1:
        j = len(text)
    return text[i + len(start):j].strip()


# ---------------------------------------------------------------------------
# Parse source text
# ---------------------------------------------------------------------------
text = read_clean_text(SRC)

# Strip the leading metadata block (keep it for header context).
header_block = text.split("1. Framework Key", 1)[0].strip()

framework_text = extract_between(text, "1. Framework Key — Eight Lenses", "2. Executive Summary")
exec_text = extract_between(text, "2. Executive Summary", "3. Five Story Clusters")
clusters_text = extract_between(text, "3. Five Story Clusters", "4. Geographic Critique")
geo_text = extract_between(text, "4. Geographic Critique", "5. Alternative Scenarios")
alt_text = extract_between(text, "5. Alternative Scenarios — What Would Upend the Current Narrative", "6. Top 4 Actions")
actions_text = extract_between(text, "6. Top 4 Actions for a Decision-Maker", "7. What It Means")
synth_text = extract_between(text, "7. What It Means — Synthesis Across All Eight Lenses")

# Executive summary sub-sections
tl_text = extract_between(exec_text, "tl;dr", "What We Don't Know")
unknown_text = extract_between(exec_text, "What We Don't Know", "Seven Calibrated Predictions")
preds_text = extract_between(exec_text, "Seven Calibrated Predictions", "Confidence Dashboard")
dash_text = extract_between(exec_text, "Confidence Dashboard")


# ---------------------------------------------------------------------------
# Helpers for the Executive Summary
# ---------------------------------------------------------------------------
def format_unknowns(txt: str) -> str:
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    items = []
    cur_q = None
    cur_a = []
    for ln in lines:
        if ln.endswith("?") and not cur_q:
            cur_q = ln
        elif cur_q and (ln[0].isupper() or ln.startswith("Will ") or ln.startswith("Can ") or ln.startswith("How ")):
            # New question started.
            items.append((cur_q, " ".join(cur_a)))
            cur_q = ln
            cur_a = []
        else:
            cur_a.append(ln)
    if cur_q:
        items.append((cur_q, " ".join(cur_a)))
    lis = []
    for q, a in items:
        lis.append(f'<li><strong class="question">{esc(q)}</strong> {esc(a)}</li>')
    return f'<ul class="unknowns">\n{"\n".join(lis)}\n</ul>'


def format_predictions(txt: str) -> str:
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    cards = []
    title = None
    body = []
    def flush():
        if title:
            cards.append(
                f'<article class="prediction-card">\n'
                f'  <h4>{esc(title)}</h4>\n'
                f'  <div class="prediction-body">{" ".join(body)}</div>\n'
                f'</article>'
            )
    for ln in lines:
        if ("?" in ln or ln.endswith(":")) and ("confidence" in ln.lower() or "valuation" in ln.lower() or "trajectory" in ln.lower() or "pace" in ln.lower() or "range" in ln.lower()):
            flush()
            title = ln
            body = []
        else:
            body.append(esc(ln))
    flush()
    return "\n".join(cards)


def format_dashboard(txt: str) -> str:
    # Extract the seven rows from the dashboard text.
    rows = [
        ["Iran peace deal within 30 days", "20%", "Iran denies deal; pattern of false dawns; no enforcement mechanism"],
        ["FISA Section 702 lapse", "95%", "House voted 218–198 against; Congress left town; no path to renewal"],
        ["Republicans lose House in midterms", "55%", "Cornyn predicts “disaster”; inflation 4.2%; Trump endorsements faltering"],
        ["UK government falls within 6 months", "35%", "Healey resignation serious but not fatal; Labour holds majority"],
        ["SpaceX IPO valuation at $1.77T / $135", "—", "Pre-IPO valuation; single price, no range; subject to market conditions"],
        ["Oil $85–105/barrel in 90 days", "65%", "War premium ~30%; ECB tightening; strategic volatility"],
        ["West Bank settlement acceleration", "90%", "60 sites approved; procedures circumvented; pre-election rush"],
    ]
    thead = "<tr><th>Prediction</th><th>Confidence</th><th>Key rationale</th></tr>"
    trows = "\n".join(
        f"<tr><td>{esc(r[0])}</td><td class='conf'>{esc(r[1])}</td><td>{esc(r[2])}</td></tr>" for r in rows
    )
    return f'<table class="dashboard"><thead>{thead}</thead><tbody>{trows}</tbody></table>'


# ---------------------------------------------------------------------------
# Helpers for clusters
# ---------------------------------------------------------------------------
CLUSTER_TITLES = [
    "Cluster 1: Iran War & Geopolitical Vertigo — The 24-Hour Crisis Cycle",
    "Cluster 2: Democratic Institutions Under Pressure — The Slow Dismantling",
    "Cluster 3: The Economy — War, Inflation, and the End of Certainty",
    "Cluster 4: International Fracture — UK, Israel, Colombia, and the Migration Crisis",
    "Cluster 5: Other Notable Stories",
]


def format_cluster(cluster_text: str, title: str) -> str:
    # Remove the title line itself.
    body = cluster_text.replace(title, "", 1).strip()
    # Split into subsections by known markers.
    narrative = extract_between(body, "", "Key people and quotes:")
    people = extract_between(body, "Key people and quotes:", "Key data points:")
    data = extract_between(body, "Key data points:", "Analytical lens insights")
    lenses = extract_between(body, "Analytical lens insights")

    out = [f'<section class="cluster">', f'<h3>{esc(title)}</h3>']
    if narrative:
        out.append(f'<div class="cluster-narrative">{paragraphs(narrative)}</div>')

    if people:
        out.append('<div class="cluster-quotes">')
        out.append('<h4>Key people and quotes</h4>')
        # Each quote line usually: Name (title):  "Quote..."
        quote_lines = [ln.strip() for ln in people.splitlines() if ln.strip()]
        for ql in quote_lines:
            # Split on first occurrence of ':  '
            m = re.match(r"^(.+?):\s*(.+)$", ql)
            if m:
                attribution, quote = m.group(1).strip(), m.group(2).strip()
                out.append(
                    f'<blockquote>\n'
                    f'  <p>{esc(quote)}</p>\n'
                    f'  <cite>— {esc(attribution)}</cite>\n'
                    f'</blockquote>'
                )
            else:
                out.append(f"<p>{esc(ql)}</p>")
        out.append('</div>')

    if data:
        out.append('<div class="cluster-data">')
        out.append('<h4>Key data points</h4>')
        out.append(bullets(data))
        out.append('</div>')

    if lenses:
        out.append('<div class="cluster-lenses">')
        out.append('<h4>Analytical lens insights</h4>')
        out.append(bullets(lenses))
        out.append('</div>')

    out.append('</section>')
    return "\n".join(out)


clusters_html = []
for i, title in enumerate(CLUSTER_TITLES):
    if title in clusters_text:
        start = clusters_text.find(title)
        end = clusters_text.find(CLUSTER_TITLES[i + 1]) if i + 1 < len(CLUSTER_TITLES) else len(clusters_text)
        chunk = clusters_text[start:end].strip()
        clusters_html.append(format_cluster(chunk, title))


# ---------------------------------------------------------------------------
# Geographic critique
# ---------------------------------------------------------------------------
GEO_REGIONS = [
    "United States",
    "Middle East / Iran",
    "Europe",
    "Latin America",
    "Africa",
    "Asia-Pacific",
    "Canada",
]


def format_geo(txt: str) -> str:
    cards = []
    for i, region in enumerate(GEO_REGIONS):
        marker = region + " ("
        start = txt.find(marker)
        if start == -1:
            continue
        end = txt.find(GEO_REGIONS[i + 1] + " (") if i + 1 < len(GEO_REGIONS) else len(txt)
        chunk = txt[start:end].strip()
        # Title line includes region and article share.
        title_line = chunk.split("\n", 1)[0].strip()
        body = chunk[len(title_line):].strip()
        cards.append(
            f'<article class="geo-card">\n'
            f'  <h4>{esc(title_line)}</h4>\n'
            f'  {paragraphs(body)}\n'
            f'</article>'
        )
    return "\n".join(cards)


geo_html = format_geo(geo_text)


# ---------------------------------------------------------------------------
# Alternative scenarios
# ---------------------------------------------------------------------------
def format_scenarios(txt: str) -> str:
    cards = []
    # Split by Scenario N:
    parts = re.split(r'(?=Scenario \d+)', txt.strip())
    for part in parts:
        part = part.strip()
        if not part.startswith("Scenario"):
            continue
        m = re.match(r"(Scenario \d+:.*?)\n", part)
        if m:
            title = m.group(1).strip()
            body = part[m.end():].strip()
            # Probability line at end usually.
            prob_match = re.search(r"Probability:\s*(\d+%)", body)
            prob = prob_match.group(1) if prob_match else ""
            if prob_match:
                body = body[:prob_match.start()].strip()
            cards.append(
                f'<article class="scenario-card">\n'
                f'  <h4>{esc(title)} <span class="prob">{esc(prob)}</span></h4>\n'
                f'  {paragraphs(body)}\n'
                f'</article>'
            )
    return "\n".join(cards)


scenarios_html = format_scenarios(alt_text)


# ---------------------------------------------------------------------------
# Top actions
# ---------------------------------------------------------------------------
def format_actions(txt: str) -> str:
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    items = []
    cur_title = None
    cur_body = []
    def flush():
        if cur_title:
            items.append(
                f'<li class="action-item">\n'
                f'  <strong>{esc(cur_title)}</strong>\n'
                f'  <ul class="sub-actions">\n' +
                "\n".join(f"    <li>{esc(b)}</li>" for b in cur_body) +
                '\n  </ul>\n'
                f'</li>'
            )
    for ln in lines:
        if re.match(r"^\d+\.\s", ln):
            flush()
            cur_title = re.sub(r"^\d+\.\s*", "", ln).strip()
            cur_body = []
        else:
            cur_body.append(ln)
    flush()
    return f'<ol class="actions">\n{"\n".join(items)}\n</ol>'


actions_html = format_actions(actions_text)


# ---------------------------------------------------------------------------
# Observer section (source PDF does not include observer commentaries)
# ---------------------------------------------------------------------------
observers_html = '''
<section id="observers" class="section">
  <h2 class="section-title">Observer Commentaries</h2>
  <p class="section-note">The source PDF for June 12, 2026 does not contain observer commentary sections. The three observer lenses that normally accompany this briefing are listed below for reference.</p>
  <div class="observer-grid">
    <article class="observer-card">
      <div class="observer-header">
        <div class="avatar" aria-hidden="true">翟</div>
        <div>
          <h3>翟东升</h3>
          <div class="observer-tag">主权信用货币论 · 平行体系理论 · 经济战框架</div>
        </div>
      </div>
      <blockquote class="observer-quote">
        Observer commentary not present in the June 12 source PDF.
      </blockquote>
    </article>
    <article class="observer-card">
      <div class="observer-header">
        <div class="avatar" aria-hidden="true">金</div>
        <div>
          <h3>金灿荣</h3>
          <div class="observer-tag">百年变局 · 金式幽默 · 自信直白</div>
        </div>
      </div>
      <blockquote class="observer-quote">
        Observer commentary not present in the June 12 source PDF.
      </blockquote>
    </article>
    <article class="observer-card">
      <div class="observer-header">
        <div class="avatar" aria-hidden="true">宋</div>
        <div>
          <h3>宋鸿兵</h3>
          <div class="observer-tag">美元环流 · 金融高边疆 · 三变六反 · 工程系统思维</div>
        </div>
      </div>
      <blockquote class="observer-quote">
        Observer commentary not present in the June 12 source PDF.
      </blockquote>
    </article>
  </div>
</section>
'''


# ---------------------------------------------------------------------------
# Lens framework table
# ---------------------------------------------------------------------------
lens_rows = [
    ("Mao (Dialectics)", "Principal contradiction; antagonistic vs. non-antagonistic; contradictions accelerating", "Trump's executive will vs. institutional resistance; Iran war as transforming contradiction"),
    ("Laozi (Dao De Jing)", "Wu wei (effortless action); fan (reversal); over-assertion breeds backlash", "Trump's yang excess; Sheinbaum's over-assertion breeds backlash"),
    ("Nietzsche (Will to Power)", "Will to power; Übermensch; ressentiment; inversion of values", "De La Espriella's machismo; DOJ election fraud campaign as ressentiment; Richter as Übermensch"),
    ("Sun Tzu (Art of War)", "Positioning; know self/enemy; terrains; shih (strategic advantage)", "Iran holds positional advantage; Trump does not know his own forces' will; elite power occupies self-defined terrain"),
    ("Mao (Strategic Phases)", "Strategic offensive/defensive/stalemate; base areas; protracted vs. quick-decision war", "Iran fights protracted war; Trump wants quick-decision; Israel's settlement base-area strategy"),
    ("Clausewitz (On War)", "Center of gravity; friction; fog; war as politics by other means", "US center of gravity = domestic political will; friction dominates every story; fog is deliberate strategy"),
    ("Han Fei (Legalism)", "Fa (law), shu (ruler's tactics), shi (power-position); rule of law vs. impulse governance", "FISA collapse as fa failure; no binding framework for Iran escalation; Pulte appointment as shu over fa"),
    ("Zeng Guofan (Discipline)", "Zhuo (doggedness); meticulous preparation; incremental accumulation", "Settlement movement's relentless ground-game; young housing activists' zoning-by-zoning approach"),
    ("Mao (On Practice)", "Knowledge arises from practice; investigation before action; dialectical relationship between theory and practice", "DOJ ignores On Practice — charges before evidence, allegations before investigation; young housing activists investigate local conditions"),
    ("Drucker (Management)", "Do the right things (effectiveness) vs. do things right (efficiency); mission clarity; resource allocation", "ECB's rate hike as Druckerian effectiveness; Starmer's trilemma; Musk's mission-driven market dominance"),
    ("Connector (Polyvagal)", "Ventral vagal (safety); sympathetic (danger); dorsal vagal (life-threat); emotional undercurrents", "Dominant state = sympathetic (hypervigilance); islands of ventral vagal in sports, arts, housing activism; dorsal zones in deportation, assassination"),
]

lens_tbody = "\n".join(
    f"<tr><td class='lens-name'>{esc(name)}</td><td>{esc(core)}</td><td>{esc(app)}</td></tr>"
    for name, core, app in lens_rows
)
lens_table = f'''
<table class="lens-table">
  <thead>
    <tr><th>Lens</th><th>Core idea</th><th>Primary application</th></tr>
  </thead>
  <tbody>
    {lens_tbody}
  </tbody>
</table>
'''


# ---------------------------------------------------------------------------
# Key indicators block
# ---------------------------------------------------------------------------
key_indicators = [
    "S&P 500: +1.8% on peace hopes",
    "Brent crude: $90.38/barrel, down 4%",
    "WTI: $87.71/barrel, down 2.6% (extended trading &gt;4%)",
    "US gasoline: $4.13/gallon, up 39% since war began",
    "US diesel: $5.28/gallon, up 40% since war began",
    "US CPI inflation: 4.2% in May (up from 2.4% before war)",
    "Eurozone inflation: 3.2% in May",
    "ECB key rate: 2.25% (first increase since Sept 2023)",
    "World Bank global growth: 2.5% in 2026 (could fall to 1.3%)",
    "World Bank global inflation: 4.0% in 2026 (up from 3.3%)",
    "Commodity prices: 22% rise since war began",
    "USMCA governs $2 trillion in annual trilateral trade",
    "SpaceX IPO valuation: $1.77T at $135/share",
    "FISA 702 extension vote: 218–198 against in House",
    "West Bank: 60 new sites, 80% increase in settlements since late 2022, $340M in roads",
]

indicators_html = '<div class="indicators-grid">' + "\n".join(
    f'<div class="indicator"><span class="indicator-dot"></span>{esc(item)}</div>' for item in key_indicators
) + '</div>'


# ---------------------------------------------------------------------------
# Assemble full HTML
# ---------------------------------------------------------------------------
html_doc = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NYT Strategic Briefing · Global Signal · June 12, 2026</title>
  <meta name="description" content="Self-contained NYT Strategic Briefing for June 12, 2026 — Global Signal edition.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;0,6..72,700;1,6..72,400&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0a0e1a;
      --bg-soft: #0f1424;
      --surface: rgba(255, 255, 255, 0.04);
      --surface-hover: rgba(255, 255, 255, 0.07);
      --text: #e8e6df;
      --text-muted: #9ca3af;
      --gold: #c9a84c;
      --gold-dim: rgba(201, 168, 76, 0.15);
      --cyan: #4a9eff;
      --cyan-dim: rgba(74, 158, 255, 0.12);
      --border: rgba(255, 255, 255, 0.06);
      --shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
      --radius: 14px;
      --max-width: 1200px;
      --font-sans: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      --font-serif: 'Newsreader', Georgia, 'Times New Roman', serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-serif);
      font-size: 17px;
      line-height: 1.7;
      -webkit-font-smoothing: antialiased;
    }}
    a {{ color: var(--cyan); text-decoration: none; transition: color 0.2s; }}
    a:hover {{ color: var(--gold); }}
    .top-bar {{
      position: sticky;
      top: 0;
      z-index: 50;
      background: rgba(10, 14, 26, 0.85);
      backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--border);
    }}
    .top-bar-inner {{
      max-width: var(--max-width);
      margin: 0 auto;
      padding: 0.85rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }}
    .back-link {{
      font-family: var(--font-sans);
      font-size: 0.85rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }}
    .back-link::before {{
      content: "←";
      color: var(--gold);
    }}
    .edition {{
      font-family: var(--font-sans);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--gold);
      font-weight: 700;
    }}
    header.hero {{
      max-width: var(--max-width);
      margin: 0 auto;
      padding: 4rem 1.5rem 3rem;
      text-align: center;
      border-bottom: 1px solid var(--border);
    }}
    .kicker {{
      font-family: var(--font-sans);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: var(--cyan);
      font-weight: 700;
      margin-bottom: 0.75rem;
    }}
    h1 {{
      font-family: var(--font-sans);
      font-size: clamp(2rem, 5vw, 3.4rem);
      font-weight: 700;
      letter-spacing: -0.03em;
      margin: 0 0 0.5rem;
      line-height: 1.1;
    }}
    .hero h1 span {{ color: var(--gold); }}
    .hero .subtitle {{
      font-family: var(--font-serif);
      font-size: 1.35rem;
      color: var(--text-muted);
      font-style: italic;
      margin: 0.5rem 0 0;
    }}
    .hero .date-line {{
      font-family: var(--font-sans);
      font-size: 0.95rem;
      color: var(--text-muted);
      margin-top: 1rem;
      letter-spacing: 0.05em;
    }}
    main {{
      max-width: var(--max-width);
      margin: 0 auto;
      padding: 2.5rem 1.5rem 5rem;
    }}
    .section {{
      margin-bottom: 3.5rem;
    }}
    .section-title {{
      font-family: var(--font-sans);
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.01em;
      margin: 0 0 1.25rem;
      padding-bottom: 0.6rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }}
    .section-title::before {{
      content: "";
      display: inline-block;
      width: 5px;
      height: 1.1em;
      background: linear-gradient(180deg, var(--gold), var(--cyan));
      border-radius: 3px;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.75rem;
      backdrop-filter: blur(12px);
      box-shadow: var(--shadow);
      transition: transform 0.2s, background 0.2s;
    }}
    .card:hover {{ background: var(--surface-hover); }}
    p {{ margin: 0 0 1rem; }}
    .lead {{
      font-size: 1.15rem;
      line-height: 1.8;
      color: var(--text);
    }}
    .indicators-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 0.85rem;
    }}
    .indicator {{
      display: flex;
      align-items: flex-start;
      gap: 0.65rem;
      font-family: var(--font-sans);
      font-size: 0.9rem;
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.85rem 1rem;
    }}
    .indicator-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--gold);
      margin-top: 0.5rem;
      flex-shrink: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-family: var(--font-sans);
      font-size: 0.92rem;
      margin: 1rem 0;
    }}
    th, td {{
      padding: 0.85rem 0.75rem;
      text-align: left;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    th {{
      color: var(--gold);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.08em;
      background: var(--bg-soft);
    }}
    td {{ color: var(--text); }}
    .lens-name {{ color: var(--cyan); font-weight: 600; white-space: nowrap; }}
    .conf {{ color: var(--gold); font-weight: 700; font-variant-numeric: tabular-nums; }}
    ul, ol {{ margin: 0 0 1rem 1.25rem; padding: 0; }}
    li {{ margin-bottom: 0.5rem; }}
    .unknowns {{ list-style: none; margin-left: 0; }}
    .unknowns li {{
      background: var(--surface);
      border-left: 3px solid var(--cyan);
      padding: 1rem 1.25rem;
      border-radius: 0 var(--radius) var(--radius) 0;
      margin-bottom: 0.85rem;
    }}
    .question {{ display: block; color: var(--cyan); margin-bottom: 0.35rem; }}
    .prediction-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.35rem;
      margin-bottom: 1rem;
      backdrop-filter: blur(10px);
    }}
    .prediction-card h4 {{ margin: 0 0 0.5rem; color: var(--gold); font-family: var(--font-sans); font-size: 1.05rem; }}
    .prediction-body {{ color: var(--text-muted); font-size: 0.95rem; }}
    .cluster-grid {{
      display: grid;
      gap: 1.25rem;
    }}
    .cluster {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.75rem;
      backdrop-filter: blur(10px);
    }}
    .cluster h3 {{
      font-family: var(--font-sans);
      font-size: 1.15rem;
      color: var(--gold);
      margin: 0 0 1rem;
      line-height: 1.35;
    }}
    .cluster h4 {{
      font-family: var(--font-sans);
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--cyan);
      margin: 1.5rem 0 0.75rem;
    }}
    .cluster-narrative p {{ font-size: 1.02rem; }}
    blockquote {{
      margin: 0.75rem 0 1rem;
      padding: 0.75rem 1rem;
      border-left: 3px solid var(--gold);
      background: var(--gold-dim);
      border-radius: 0 8px 8px 0;
      font-style: italic;
    }}
    blockquote p {{ margin: 0 0 0.35rem; }}
    blockquote cite {{
      display: block;
      font-size: 0.85rem;
      font-style: normal;
      color: var(--text-muted);
      font-family: var(--font-sans);
    }}
    .geo-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 1rem;
    }}
    .geo-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.35rem;
      backdrop-filter: blur(10px);
    }}
    .geo-card h4 {{ margin: 0 0 0.75rem; color: var(--cyan); font-family: var(--font-sans); font-size: 1rem; }}
    .scenario-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 1rem;
    }}
    .scenario-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.35rem;
      backdrop-filter: blur(10px);
    }}
    .scenario-card h4 {{ margin: 0 0 0.75rem; font-family: var(--font-sans); font-size: 1rem; color: var(--gold); }}
    .scenario-card .prob {{ color: var(--cyan); font-weight: 700; margin-left: 0.5rem; }}
    .actions {{
      list-style: none;
      margin-left: 0;
      counter-reset: action;
    }}
    .action-item {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.35rem;
      margin-bottom: 1rem;
      backdrop-filter: blur(10px);
      position: relative;
      padding-left: 3.5rem;
    }}
    .action-item::before {{
      counter-increment: action;
      content: counter(action);
      position: absolute;
      left: 1.25rem;
      top: 1.25rem;
      width: 1.6rem;
      height: 1.6rem;
      display: grid;
      place-items: center;
      border-radius: 50%;
      background: var(--gold);
      color: #0a0e1a;
      font-family: var(--font-sans);
      font-weight: 700;
      font-size: 0.85rem;
    }}
    .action-item strong {{ display: block; color: var(--gold); font-family: var(--font-sans); margin-bottom: 0.75rem; }}
    .sub-actions {{ margin-left: 1.25rem; color: var(--text-muted); }}
    .observer-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1.25rem;
    }}
    @media (max-width: 900px) {{
      .observer-grid {{ grid-template-columns: 1fr; }}
    }}
    .observer-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.5rem;
      backdrop-filter: blur(10px);
    }}
    .observer-header {{
      display: flex;
      align-items: center;
      gap: 1rem;
      margin-bottom: 1rem;
    }}
    .avatar {{
      width: 3rem;
      height: 3rem;
      border-radius: 50%;
      background: linear-gradient(135deg, var(--gold-dim), var(--cyan-dim));
      border: 1px solid var(--border);
      display: grid;
      place-items: center;
      font-family: var(--font-sans);
      font-weight: 700;
      color: var(--gold);
      font-size: 1.25rem;
    }}
    .observer-card h3 {{ margin: 0; font-family: var(--font-sans); font-size: 1.15rem; color: var(--text); }}
    .observer-tag {{ font-size: 0.78rem; color: var(--text-muted); margin-top: 0.2rem; }}
    .observer-quote {{
      border-left-color: var(--cyan);
      background: var(--cyan-dim);
      margin: 0;
      font-size: 0.95rem;
      color: var(--text-muted);
    }}
    .section-note {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1rem 1.25rem;
      color: var(--text-muted);
      font-size: 0.95rem;
      margin-bottom: 1.25rem;
    }}
    footer.site-footer {{
      max-width: var(--max-width);
      margin: 0 auto;
      padding: 2.5rem 1.5rem;
      border-top: 1px solid var(--border);
      text-align: center;
      color: var(--text-muted);
      font-family: var(--font-sans);
      font-size: 0.85rem;
    }}
    footer.site-footer a {{ color: var(--gold); }}
    @media (max-width: 700px) {{
      .hero {{ padding: 2.5rem 1rem 2rem; }}
      main {{ padding: 1.5rem 1rem 3rem; }}
      .card {{ padding: 1.25rem; }}
      .cluster {{ padding: 1.25rem; }}
      .top-bar-inner {{ flex-wrap: wrap; }}
    }}
  </style>
</head>
<body>
  <div class="top-bar">
    <div class="top-bar-inner">
      <a class="back-link" href="../archive.html">Back to Gallery</a>
      <span class="edition">Global Signal · June 12, 2026</span>
    </div>
  </div>

  <header class="hero">
    <div class="kicker">The New York Times</div>
    <h1>NYT Strategic Briefing <span>Global Signal</span></h1>
    <p class="subtitle">Morning intelligence briefing from 40 NYT articles and analytical supplements</p>
    <p class="date-line">June 12, 2026 · Date of Analysis: June 12, 2026</p>
  </header>

  <main>
    <section id="executive-summary" class="section">
      <h2 class="section-title">Executive Summary</h2>
      <div class="card">
        <div class="lead">{paragraphs(tl_text)}</div>
      </div>
    </section>

    <section id="data-points" class="section">
      <h2 class="section-title">Key Data Points</h2>
      {indicators_html}
      <h3 style="margin: 2rem 0 1rem; font-family: var(--font-sans); font-size: 1.05rem; color: var(--cyan);">Eight-Lens Framework</h3>
      {lens_table}
    </section>

    <section id="unknowns" class="section">
      <h2 class="section-title">What We Don’t Know</h2>
      <div class="card">
        {format_unknowns(unknown_text)}
      </div>
    </section>

    <section id="predictions" class="section">
      <h2 class="section-title">Seven Calibrated Predictions</h2>
      {format_predictions(preds_text)}
    </section>

    <section id="dashboard" class="section">
      <h2 class="section-title">Confidence Dashboard</h2>
      <div class="card">
        {format_dashboard(dash_text)}
      </div>
    </section>

    <section id="clusters" class="section">
      <h2 class="section-title">Cluster Analysis</h2>
      <div class="cluster-grid">
        {"\n".join(clusters_html)}
      </div>
    </section>

    {observers_html}

    <section id="scenarios" class="section">
      <h2 class="section-title">Alternative Scenarios</h2>
      <div class="scenario-grid">
        {scenarios_html}
      </div>
    </section>

    <section id="actions" class="section">
      <h2 class="section-title">Top 4 Actions for a Decision-Maker</h2>
      {actions_html}
    </section>

    <section id="synthesis" class="section">
      <h2 class="section-title">What It Means — Synthesis Across All Eight Lenses</h2>
      <div class="card">
        {paragraphs(synth_text)}
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <p>Prepared by Hermes Agent · Morning Briefing Pipeline</p>
    <p><a href="../archive.html">View the briefing gallery</a> · <a href="#top">Back to top</a></p>
  </footer>
</body>
</html>
'''

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html_doc)

print(f"Wrote {OUT} ({len(html_doc):,} characters)")
