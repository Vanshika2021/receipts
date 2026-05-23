"""
Rebuild ALL person pages from ClickHouse data.
Run this to sync pages with database.
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

def build_page(person_name: str, promises: list) -> str:
    slug = person_name.lower().replace(" ", "-")
    
    rows = ""
    for p in promises:
        promise, deadline, source_url, status, evidence = p
        
        verdict_map = {
            "✅ Kept": ("kept", "#22c55e", "✅"),
            "❌ Broken": ("broken", "#ef4444", "❌"),
            "⚠️ Partial": ("partial", "#f59e0b", "⚠️"),
            "❓ Unclear": ("unclear", "#94a3b8", "❓"),
            "pending": ("pending", "#94a3b8", "⏳"),
            "checking": ("pending", "#94a3b8", "⏳"),
        }
        verdict_key, color, emoji = verdict_map.get(status, ("pending", "#94a3b8", "⏳"))
        
        source_html = f'<a href="{source_url}" target="_blank">🔗 Source</a>' if source_url else "<span style='color:#475569'>—</span>"
        evidence_text = evidence if evidence else "Deadline not yet reached"
        
        rows += f"""
        <tr>
            <td>{promise}</td>
            <td>{deadline}</td>
            <td style="color:{color};font-weight:bold">{emoji} {verdict_key.title()}</td>
            <td>{evidence_text}</td>
            <td>{source_html}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Receipts — {person_name}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 1000px; margin: 40px auto; padding: 0 20px; background: #0f172a; color: #e2e8f0; }}
  h1 {{ color: #00D4AA; }} h2 {{ color: #94a3b8; font-size: 1rem; margin-bottom: 16px; }}
  p {{ color: #94a3b8; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
  th {{ background: #1e293b; padding: 12px; text-align: left; color: #00D4AA; }}
  td {{ padding: 12px; border-bottom: 1px solid #1e293b; vertical-align: top; font-size: 0.9rem; }}
  tr:hover td {{ background: #1e293b; }}
  .footer {{ margin-top: 40px; color: #475569; font-size: 0.8rem; text-align: center; padding: 20px 0; border-top: 1px solid #1e293b; }}
  a {{ color: #00D4AA; text-decoration: none; }}
  .back {{ display: inline-block; margin-bottom: 20px; color: #00D4AA; }}
</style>
</head>
<body>
<a href="index.html" class="back">← Back to all people</a>
<h1>🧾 Did {person_name} Keep Their Promises?</h1>
<h2>AI-powered public accountability — tracked by <a href="https://vanshika2021.github.io/receipts/">Receipts</a></h2>
<p>Analyzed: {datetime.now().strftime('%B %d, %Y')} · {len(promises)} promises tracked</p>
<table>
  <tr><th>Promise</th><th>Deadline</th><th>Verdict</th><th>Evidence</th><th>Source</th></tr>
  {rows}
</table>
<div class="footer">
  Built at <strong>Agentic Engineering Hack 2026</strong> · 
  Powered by Nimble, ClickHouse, Senso, Claude, Datadog ·
  <a href="https://github.com/Vanshika2021/receipts">GitHub</a>
</div>
</body>
</html>"""
    
    return html, slug

def rebuild_all():
    print("🔄 Rebuilding all pages from ClickHouse...")
    db = get_db()
    
    # Get all people
    people = db.query("SELECT DISTINCT person FROM promises ORDER BY person").result_rows
    
    docs_path = os.path.join(os.path.dirname(__file__), "docs")
    os.makedirs(docs_path, exist_ok=True)
    
    for (person_name,) in people:
        # Get all promises for this person
        result = db.query("""
            SELECT promise, deadline, source_url, status, evidence
            FROM promises WHERE person = %(person)s
            ORDER BY created_at ASC
        """, parameters={"person": person_name})
        
        promises = result.result_rows
        if not promises:
            continue
            
        html, slug = build_page(person_name, promises)
        
        file_path = os.path.join(docs_path, f"{slug}.html")
        with open(file_path, "w") as f:
            f.write(html)
        
        print(f"  ✅ {person_name}: {len(promises)} promises → {slug}.html")
    
    # Git push
    repo_dir = os.path.dirname(__file__)
    subprocess.run(["git", "add", "docs/"], cwd=repo_dir, capture_output=True)
    result = subprocess.run(["git", "commit", "-m", "Rebuild all pages from ClickHouse"], cwd=repo_dir, capture_output=True, text=True)
    push = subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, text=True, timeout=15)
    
    if push.returncode == 0:
        print(f"\n✅ All pages pushed to GitHub Pages!")
        print(f"🌐 https://vanshika2021.github.io/receipts/")
    else:
        print(f"⚠️ Push failed: {push.stderr[:100]}")

if __name__ == "__main__":
    rebuild_all()
