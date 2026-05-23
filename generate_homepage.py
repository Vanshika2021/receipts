"""
Generate a homepage for Receipts showing all tracked people with stats.
Pulls live data from ClickHouse and writes to docs/index.html
"""

import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv
import clickhouse_connect

load_dotenv()

def get_db():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST"),
        port=int(os.getenv("CLICKHOUSE_PORT", 8443)),
        username=os.getenv("CLICKHOUSE_USER"),
        password=os.getenv("CLICKHOUSE_PASSWORD"),
        secure=True
    )

def generate_homepage():
    print("🏠 Generating homepage from ClickHouse data...")
    
    db = get_db()
    
    # Get all people and their promise counts
    people_result = db.query("""
        SELECT 
            person,
            count(*) as total,
            countIf(status = '✅ Kept') as kept,
            countIf(status = '❌ Broken') as broken,
            countIf(status = '⚠️ Partial') as partial,
            countIf(status = '❓ Unclear') as unclear,
            countIf(status = 'pending') as pending,
            countIf(status = 'checking') as checking
        FROM promises
        GROUP BY person
        ORDER BY total DESC
    """)
    
    # Get total stats
    total_result = db.query("""
        SELECT 
            count(*) as total,
            countIf(status = '✅ Kept') as kept,
            countIf(status = '❌ Broken') as broken,
            countIf(status = '⚠️ Partial') as partial
        FROM promises
    """)
    
    total_row = total_result.result_rows[0] if total_result.result_rows else (0,0,0,0)
    total_promises = total_row[0]
    total_kept = total_row[1]
    total_broken = total_row[2]
    total_partial = total_row[3]
    
    # Build person cards
    cards = ""
    for row in people_result.result_rows:
        person, total, kept, broken, partial, unclear, pending, checking = row
        slug = person.lower().replace(" ", "-")
        
        # Calculate keep rate
        checked = kept + broken + partial
        keep_rate = int((kept / checked * 100)) if checked > 0 else None
        keep_rate_html = f'<span class="keep-rate">{"🟢" if keep_rate and keep_rate >= 50 else "🔴"} {keep_rate}% kept</span>' if keep_rate is not None else '<span class="keep-rate">⏳ Pending</span>'
        
        # Verdict bar
        bar_html = ""
        if checked > 0:
            kept_pct = int(kept/total*100)
            broken_pct = int(broken/total*100)
            partial_pct = int(partial/total*100)
            unclear_pct = int(unclear/total*100)
            pending_pct = 100 - kept_pct - broken_pct - partial_pct - unclear_pct
            bar_html = f"""
            <div class="verdict-bar">
                <div style="width:{kept_pct}%;background:#22c55e" title="Kept: {kept}"></div>
                <div style="width:{broken_pct}%;background:#ef4444" title="Broken: {broken}"></div>
                <div style="width:{partial_pct}%;background:#f59e0b" title="Partial: {partial}"></div>
                <div style="width:{unclear_pct}%;background:#94a3b8" title="Unclear: {unclear}"></div>
                <div style="width:{pending_pct}%;background:#1e293b" title="Pending: {pending + checking}"></div>
            </div>"""
        
        cards += f"""
        <a href="{slug}.html" class="card">
            <div class="card-header">
                <h2>{person}</h2>
                {keep_rate_html}
            </div>
            <div class="stats">
                <span title="Total">📋 {total} promises</span>
                <span title="Kept">✅ {kept}</span>
                <span title="Broken">❌ {broken}</span>
                <span title="Pending">⏳ {pending + checking}</span>
            </div>
            {bar_html}
        </a>"""
    
    if not cards:
        cards = '<p style="color:#94a3b8;text-align:center">No data yet. Run the agent to track promises.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Receipts — Public Promise Tracker</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
  
  header {{ padding: 40px 20px; text-align: center; border-bottom: 1px solid #1e293b; }}
  header h1 {{ font-size: 2.5rem; color: #00D4AA; margin-bottom: 8px; }}
  header p {{ color: #94a3b8; font-size: 1.1rem; max-width: 600px; margin: 0 auto; }}
  
  .global-stats {{ display: flex; justify-content: center; gap: 40px; padding: 30px 20px; background: #1e293b; }}
  .stat {{ text-align: center; }}
  .stat-number {{ font-size: 2rem; font-weight: bold; color: #00D4AA; }}
  .stat-label {{ color: #94a3b8; font-size: 0.85rem; margin-top: 4px; }}
  
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; padding: 40px 20px; max-width: 1200px; margin: 0 auto; }}
  
  .card {{ background: #1e293b; border-radius: 12px; padding: 24px; text-decoration: none; color: inherit; border: 1px solid #334155; transition: all 0.2s; display: block; }}
  .card:hover {{ border-color: #00D4AA; transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,212,170,0.15); }}
  
  .card-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }}
  .card-header h2 {{ font-size: 1.2rem; color: #f1f5f9; }}
  .keep-rate {{ font-size: 0.85rem; color: #94a3b8; white-space: nowrap; margin-left: 8px; }}
  
  .stats {{ display: flex; gap: 12px; font-size: 0.85rem; color: #94a3b8; margin-bottom: 12px; flex-wrap: wrap; }}
  
  .verdict-bar {{ display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: #0f172a; }}
  .verdict-bar div {{ height: 100%; }}
  
  .legend {{ display: flex; gap: 16px; justify-content: center; padding: 0 20px 20px; flex-wrap: wrap; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 0.8rem; color: #94a3b8; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  
  footer {{ text-align: center; padding: 40px 20px; color: #475569; font-size: 0.8rem; border-top: 1px solid #1e293b; }}
  footer a {{ color: #00D4AA; text-decoration: none; }}
  
  .updated {{ text-align: center; color: #475569; font-size: 0.8rem; padding: 10px; }}
</style>
</head>
<body>

<header>
  <h1>🧾 Receipts</h1>
  <p>AI-powered public accountability. We track what powerful people promise — and whether they deliver.</p>
</header>

<div class="global-stats">
  <div class="stat">
    <div class="stat-number">{total_promises}</div>
    <div class="stat-label">Promises Tracked</div>
  </div>
  <div class="stat">
    <div class="stat-number" style="color:#22c55e">{total_kept}</div>
    <div class="stat-label">✅ Kept</div>
  </div>
  <div class="stat">
    <div class="stat-number" style="color:#ef4444">{total_broken}</div>
    <div class="stat-label">❌ Broken</div>
  </div>
  <div class="stat">
    <div class="stat-number" style="color:#f59e0b">{total_partial}</div>
    <div class="stat-label">⚠️ Partial</div>
  </div>
</div>

<div class="legend">
  <div class="legend-item"><div class="legend-dot" style="background:#22c55e"></div> Kept</div>
  <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div> Broken</div>
  <div class="legend-item"><div class="legend-dot" style="background:#f59e0b"></div> Partial</div>
  <div class="legend-item"><div class="legend-dot" style="background:#94a3b8"></div> Unclear</div>
  <div class="legend-item"><div class="legend-dot" style="background:#1e293b;border:1px solid #334155"></div> Pending</div>
</div>

<div class="grid">
  {cards}
</div>

<div class="updated">Last updated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</div>

<footer>
  Built at <strong>Agentic Engineering Hack 2026</strong> · 
  Powered by <a href="https://nimbleway.com">Nimble</a>, 
  <a href="https://clickhouse.com">ClickHouse</a>, 
  <a href="https://senso.ai">Senso</a>, 
  <a href="https://anthropic.com">Claude</a>, 
  <a href="https://datadoghq.com">Datadog</a> ·
  <a href="https://github.com/Vanshika2021/receipts">GitHub</a>
</footer>

</body>
</html>"""

    # Write to docs/index.html
    docs_path = os.path.join(os.path.dirname(__file__), "docs")
    os.makedirs(docs_path, exist_ok=True)
    
    with open(os.path.join(docs_path, "index.html"), "w") as f:
        f.write(html)
    
    print(f"  → Homepage written with {len(people_result.result_rows)} people")
    
    # Git push
    repo_dir = os.path.dirname(__file__)
    subprocess.run(["git", "add", "docs/index.html"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Update homepage"], cwd=repo_dir, capture_output=True)
    push = subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, text=True, timeout=15)
    
    if push.returncode == 0:
        print(f"  → ✅ Homepage live: https://vanshika2021.github.io/receipts/")
    else:
        print(f"  ⚠️ Push failed: {push.stderr[:100]}")

if __name__ == "__main__":
    generate_homepage()
