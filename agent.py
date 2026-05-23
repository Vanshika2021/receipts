"""
RECEIPTS — AI Agent that tracks whether powerful people keep their promises.
Fully dynamic — works for any public figure.
"""

import os
import re
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
import clickhouse_connect
import anthropic
from nimble_python import Nimble

load_dotenv()

NIMBLE_API_KEY      = os.getenv("NIMBLE_API_KEY")
CLICKHOUSE_HOST     = os.getenv("CLICKHOUSE_HOST")
CLICKHOUSE_USER     = os.getenv("CLICKHOUSE_USER")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD")
CLICKHOUSE_PORT     = int(os.getenv("CLICKHOUSE_PORT", 8443))
SENSO_API_KEY       = os.getenv("SENSO_API_KEY")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
nimble = Nimble(api_key=NIMBLE_API_KEY)

# ── HELPERS ──────────────────────────────────────────────────────────────────

def strip_html(html: str) -> str:
    """Extract readable text from HTML."""
    # Remove script and style blocks
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL)
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_claude_json(text: str):
    """Safely parse JSON from Claude response."""
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("[") or part.startswith("{"):
                text = part
                break
    return json.loads(text)

# ── CLICKHOUSE ───────────────────────────────────────────────────────────────

def get_db():
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        secure=True
    )

def setup_table():
    db = get_db()
    db.command("""
        CREATE TABLE IF NOT EXISTS promises (
            id          UUID DEFAULT generateUUIDv4(),
            person      String,
            company     String,
            promise     String,
            deadline    String,
            date_said   String,
            source_url  String,
            status      String DEFAULT 'pending',
            evidence    String DEFAULT '',
            page_url    String DEFAULT '',
            created_at  DateTime DEFAULT now()
        )
        ENGINE = MergeTree()
        ORDER BY id
    """)
    print("✅ ClickHouse table ready")

def get_existing_promises(person_name: str) -> list:
    """Check if we already have promises for this person."""
    db = get_db()
    result = db.query(
        "SELECT promise, deadline, status FROM promises WHERE person = %(person)s",
        parameters={"person": person_name}
    )
    return result.result_rows

# ── STEP 1: FETCH FULL ARTICLE CONTENT ───────────────────────────────────────

def fetch_url_content(url: str) -> str:
    """Fetch and extract text from a URL using Nimble."""
    try:
        response = requests.post(
            "https://sdk.nimbleway.com/v1/extract",
            headers={
                "Authorization": f"Bearer {NIMBLE_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"url": url, "render": False},
            timeout=20
        )
        if response.status_code == 200:
            data = response.json()
            html = data.get("data", {}).get("html", "")
            if html:
                text = strip_html(html)
                return text[:4000]
    except Exception as e:
        print(f"    ⚠️ Extract failed: {e}")
    return ""

# ── STEP 2: SEARCH + EXTRACT PROMISES ────────────────────────────────────────

def find_raw_statements(person_name: str) -> str:
    """Search Nimble and fetch full content from top articles."""
    print(f"\n🔍 Searching web for statements by {person_name}...")

    # Cast a wide net with varied query types
    queries = [
        f"{person_name} promised pledged committed vowed",
        f"{person_name} will by 2024 2025 2026 target",
        f"{person_name} pledge promise broken kept failed",
        f"{person_name} campaign promise policy commitment",
        f"{person_name} announced plan launch deadline",
    ]

    all_text = ""
    urls_fetched = set()

    for query in queries:
        try:
            result = nimble.search(
                query=query,
                focus="news",
                search_depth="lite"
            )
            if result and hasattr(result, 'results'):
                for r in result.results[:2]:
                    all_text += f"\nTitle: {r.title}\nDescription: {r.description}\nURL: {r.url}\n"

                    if r.url not in urls_fetched and len(urls_fetched) < 6:
                        urls_fetched.add(r.url)
                        print(f"  → Fetching: {r.title[:60]}...")
                        content = fetch_url_content(r.url)
                        if content:
                            all_text += f"Full text:\n{content}\n"
        except Exception as e:
            print(f"  ⚠️ Search failed: {e}")

    print(f"  → Got {len(all_text)} chars from {len(urls_fetched)} articles")
    return all_text

def extract_promises(person_name: str, raw_text: str) -> list:
    """Use Claude to extract concrete promises with deadlines."""
    print(f"\n🧠 Extracting promises with Claude...")

    prompt = f"""You are a research assistant analyzing public statements by {person_name}.

Extract concrete promises, pledges, commitments or goals that:
1. Have ANY timeframe — specific ("by March 2025") OR vague ("within 2 years", "this year", "soon", "by end of term")
2. Are specific enough to evaluate — not just general aspirations
3. Were made publicly by {person_name} or on behalf of their organization/government

Be generous in what you include — if it sounds like a commitment, include it.

Return a JSON array. Each item:
{{
  "promise": "what was promised",
  "deadline": "timeframe stated — use 'unspecified' if vague",
  "deadline_date": "YYYY-MM-DD best estimate, use 2025-12-31 if unclear",
  "date_said": "when this was said, or empty string",
  "company": "company/party/country or empty string",
  "source_url": "source URL or empty string"
}}

Return [] ONLY if there are truly no commitments whatsoever.
Return ONLY valid JSON. No markdown, no explanation.

TEXT TO ANALYZE:
{raw_text[:9000]}"""

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text
        promises = parse_claude_json(text)
        print(f"  → Found {len(promises)} promises dynamically")
        return promises
    except Exception as e:
        print(f"  ⚠️ Extraction failed: {e}")
        return []

# ── STEP 3: STORE IN CLICKHOUSE ──────────────────────────────────────────────

def store_promise(person_name: str, p: dict) -> str:
    db = get_db()
    status = "pending"
    try:
        if datetime.strptime(p.get("deadline_date",""), "%Y-%m-%d") < datetime.now():
            status = "checking"
    except:
        pass

    db.command("""
        INSERT INTO promises (person, company, promise, deadline, date_said, source_url, status)
        VALUES (%(person)s, %(company)s, %(promise)s, %(deadline)s, %(date_said)s, %(source_url)s, %(status)s)
    """, parameters={
        "person":     person_name,
        "company":    p.get("company", ""),
        "promise":    p.get("promise", ""),
        "deadline":   p.get("deadline", ""),
        "date_said":  p.get("date_said", ""),
        "source_url": p.get("source_url", ""),
        "status":     status,
    })
    print(f"  💾 [{status}] {p['promise'][:65]}")
    return status

# ── STEP 4: CHECK VERDICT ────────────────────────────────────────────────────

def check_verdict(person_name: str, promise_text: str, deadline: str) -> dict:
    print(f"\n⚖️  Checking: '{promise_text[:55]}...'")

    evidence_text = ""
    try:
        result = nimble.search(
            query=f"{person_name} {promise_text[:45]} completed achieved announced result",
            focus="news",
            search_depth="lite"
        )
        if result and hasattr(result, 'results'):
            for r in result.results[:3]:
                evidence_text += f"Title: {r.title}\nDescription: {r.description}\nURL: {r.url}\n\n"
    except Exception as e:
        print(f"  ⚠️ Evidence search failed: {e}")

    prompt = f"""Did {person_name} keep this promise?

Promise: "{promise_text}"
Deadline: {deadline}

Web evidence:
{evidence_text[:3000] if evidence_text else "No specific evidence found."}

Return ONLY this JSON, no markdown:
{{
  "verdict": "kept" or "broken" or "partial" or "unclear",
  "confidence": 0.0 to 1.0,
  "summary": "one sentence explaining the verdict based on evidence",
  "evidence_url": "most relevant URL from evidence, or empty string"
}}"""

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        verdict = parse_claude_json(response.content[0].text)
        emoji = {"kept":"✅","broken":"❌","partial":"⚠️","unclear":"❓"}.get(verdict["verdict"],"❓")
        print(f"  → {emoji} {verdict['verdict'].upper()} (confidence: {verdict['confidence']})")
        return verdict
    except Exception as e:
        print(f"  ⚠️ Verdict failed: {e}")
        return {"verdict":"unclear","confidence":0.0,"summary":"Could not determine","evidence_url":""}

# ── STEP 5: PUBLISH TO SENSO VIA CLI ─────────────────────────────────────────

def publish_to_github_pages(person_name: str, promises_with_verdicts: list) -> str:
    """Publish verdict page to GitHub Pages."""
    print(f"\n🌐 Publishing to GitHub Pages...")

    slug = person_name.lower().replace(" ", "-")
    
    # Build HTML page
    rows = ""
    for item in promises_with_verdicts:
        v = item.get("verdict_data", {})
        emoji = {"kept":"✅","broken":"❌","partial":"⚠️","unclear":"❓","pending":"⏳"}.get(v.get("verdict","pending"),"⏳")
        color = {"kept":"#22c55e","broken":"#ef4444","partial":"#f59e0b","unclear":"#94a3b8","pending":"#94a3b8"}.get(v.get("verdict","pending"),"#94a3b8")
        
        # Source link
        source_url = item.get("source_url", "") or v.get("evidence_url", "")
        source_html = f'<a href="{source_url}" target="_blank">🔗 Source</a>' if source_url else "<span style='color:#475569'>No source</span>"
        
        rows += f"""
        <tr>
            <td>{item['promise']}</td>
            <td>{item['deadline']}</td>
            <td style="color:{color};font-weight:bold">{emoji} {v.get('verdict','pending').title()}</td>
            <td>{v.get('summary','Deadline not yet reached')}</td>
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
  h1 {{ color: #00D4AA; }} h2 {{ color: #94a3b8; font-size: 1rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
  th {{ background: #1e293b; padding: 12px; text-align: left; color: #00D4AA; }}
  td {{ padding: 12px; border-bottom: 1px solid #1e293b; vertical-align: top; font-size: 0.9rem; }}
  tr:hover td {{ background: #1e293b; }}
  .footer {{ margin-top: 40px; color: #475569; font-size: 0.8rem; }}
  a {{ color: #00D4AA; }}
</style>
</head>
<body>
<h1>🧾 Did {person_name} Keep Their Promises?</h1>
<h2>AI-powered public accountability — tracked by <a href="https://vanshika2021.github.io/receipts/">Receipts</a></h2>
<p>Analyzed: {datetime.now().strftime('%B %d, %Y')}</p>
<table>
  <tr><th>Promise</th><th>Deadline</th><th>Verdict</th><th>Evidence</th><th>Source</th></tr>
  {rows}
</table>
<div class="footer">
  Built at Agentic Engineering Hack 2026 · Powered by Nimble, ClickHouse, Senso, Claude, Datadog
</div>
</body>
</html>"""

    try:
        # Write to docs folder
        docs_path = os.path.join(os.path.dirname(__file__), "docs")
        os.makedirs(docs_path, exist_ok=True)
        
        file_path = os.path.join(docs_path, f"{slug}.html")
        with open(file_path, "w") as f:
            f.write(html)

        # Update index page
        index_path = os.path.join(docs_path, "index.md")
        with open(index_path, "a") as f:
            f.write(f"\n- [{person_name}]({slug}.html) — {datetime.now().strftime('%B %d, %Y')}")

        # Git commit and push
        import subprocess
        repo_dir = os.path.dirname(__file__)
        
        subprocess.run(["git", "add", "docs/"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Add {person_name} promise tracker"], cwd=repo_dir, capture_output=True)
        
        push = subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, text=True, timeout=15)
        
        if push.returncode == 0:
            page_url = f"https://vanshika2021.github.io/receipts/{slug}.html"
            print(f"  → ✅ Published: {page_url}")
            return page_url
        else:
            print(f"  ⚠️ Push failed: {push.stderr[:200]}")
            return ""
            
    except Exception as e:
        print(f"  ⚠️ GitHub Pages publish failed: {e}")
        return ""

def publish_to_senso(person_name: str, promises_with_verdicts: list) -> str:
    """Publish all verdicts for a person as one Senso page."""
    print(f"\n📢 Publishing to Senso...")

    # Build markdown content
    lines = [
        f"# 🧾 Did {person_name} Keep Their Promises?",
        f"\nA Receipts investigation — AI-powered public accountability.",
        f"\n*Analyzed: {datetime.now().strftime('%B %d, %Y')}*\n"
    ]

    for i, item in enumerate(promises_with_verdicts, 1):
        v = item.get("verdict_data", {})
        emoji = {"kept":"✅","broken":"❌","partial":"⚠️","unclear":"❓"}.get(v.get("verdict","unclear"),"❓")
        lines.append(f"\n## Promise {i}: {item['promise'][:80]}")
        lines.append(f"**Deadline:** {item['deadline']}")
        lines.append(f"**Verdict:** {emoji} {v.get('verdict','unclear').title()}")
        lines.append(f"**Confidence:** {int(v.get('confidence',0)*100)}%")
        if v.get('summary'):
            lines.append(f"\n{v['summary']}")
        if item.get('source_url'):
            lines.append(f"\n**Source:** {item['source_url']}")
        lines.append("\n---")

    lines.append(f"\n*Tracked by Receipts — AI-powered public accountability for journalists.*")
    content = "\n".join(lines)

    try:
        import subprocess

        senso_env = {**os.environ, "SENSO_API_KEY": SENSO_API_KEY or ""}
        if not senso_env.get("SENSO_API_KEY"):
            print("  ⚠️ No Senso API key found")
            return ""

        # Step 1: Create prompt
        prompt_result = subprocess.run([
            "senso", "prompts", "create",
            "--data", json.dumps({
                "question_text": f"Did {person_name} keep their public promises?",
                "type": "awareness"
            }),
            "--output", "json", "--quiet"
        ], capture_output=True, text=True, env=senso_env, timeout=15)

        stdout = prompt_result.stdout
        json_start = stdout.find("{")
        prompt_id = json.loads(stdout[json_start:]).get("prompt_id", "") if json_start >= 0 else ""

        if not prompt_id:
            print(f"  ⚠️ No prompt ID")
            return ""

        # Step 2: Save as draft (fast)
        draft_result = subprocess.run([
            "senso", "engine", "draft",
            "--data", json.dumps({
                "geo_question_id": prompt_id,
                "raw_markdown": content[:5000],
                "seo_title": f"{person_name} Promise Tracker — Receipts",
                "summary": f"AI-powered promise tracking for {person_name}."
            }),
            "--output", "json", "--quiet"
        ], capture_output=True, text=True, env=senso_env, timeout=15)

        if draft_result.returncode == 0:
            stdout = draft_result.stdout
            json_start = stdout.find("{")
            if json_start >= 0:
                data = json.loads(stdout[json_start:])
                content_id = data.get("content_id", "")
                print(f"  → ✅ Saved to Senso (content_id: {content_id})")
                return f"https://geo.senso.ai/drafts"
        else:
            print(f"  ⚠️ Senso draft error: {draft_result.stderr[:200]}")
        return ""

    except subprocess.TimeoutExpired:
        print(f"  ⚠️ Senso timed out")
        return ""
    except Exception as e:
        print(f"  ⚠️ Senso error: {e}")
        return ""

# ── STEP 6: UPDATE CLICKHOUSE ─────────────────────────────────────────────────

def update_verdict_in_db(person_name: str, promise_text: str, verdict: dict, page_url: str):
    db = get_db()
    verdict_map = {"kept":"✅ Kept","broken":"❌ Broken","partial":"⚠️ Partial","unclear":"❓ Unclear"}
    db.command("""
        ALTER TABLE promises UPDATE
            status=%(status)s, evidence=%(evidence)s, page_url=%(page_url)s
        WHERE person=%(person)s AND promise=%(promise)s
    """, parameters={
        "status":   verdict_map.get(verdict["verdict"],"❓ Unclear"),
        "evidence": verdict.get("summary",""),
        "page_url": page_url,
        "person":   person_name,
        "promise":  promise_text,
    })

# ── MAIN PIPELINE ────────────────────────────────────────────────────────────

def run_receipts(person_name: str):
    print(f"\n{'='*60}")
    print(f"🧾 RECEIPTS — {person_name}")
    print(f"{'='*60}")

    # Check if already processed
    existing = get_existing_promises(person_name)
    if existing:
        print(f"ℹ️  Already have {len(existing)} promises for {person_name} in database")
        print("   Running verdict check on any pending ones...\n")

    # Find promises dynamically
    raw_text = find_raw_statements(person_name)
    promises = extract_promises(person_name, raw_text) if raw_text else []

    if not promises:
        print("⚠️  No dynamic promises found — trying broader search...")
        # Broader fallback
        try:
            result = nimble.search(
                query=f"{person_name} announcement goal commitment 2025 2026",
                focus="news",
                search_depth="lite"
            )
            fallback_text = ""
            if result and hasattr(result, 'results'):
                for r in result.results[:3]:
                    fallback_text += f"Title: {r.title}\nDescription: {r.description}\n"
                    content = fetch_url_content(r.url)
                    if content:
                        fallback_text += f"Content: {content}\n\n"
            if fallback_text:
                promises = extract_promises(person_name, fallback_text)
        except:
            pass

    if not promises:
        print("❌ Could not find concrete promises. Try a CEO or politician with lots of public statements.")
        return

    print(f"\n📋 Processing {len(promises)} promises...")
    promises_with_verdicts = []

    for i, p in enumerate(promises):
        print(f"\n[{i+1}/{len(promises)}]")
        status = store_promise(person_name, p)

        verdict = None
        page_url = ""

        if status == "checking":
            verdict = check_verdict(person_name, p["promise"], p["deadline"])
            update_verdict_in_db(person_name, p["promise"], verdict, "")

        promises_with_verdicts.append({
            "promise": p["promise"],
            "deadline": p["deadline"],
            "source_url": p.get("source_url", ""),
            "verdict_data": verdict or {"verdict": "pending", "confidence": 0, "summary": "Deadline not yet reached"}
        })

    # Pull ALL promises for this person from ClickHouse for the full page
    try:
        db = get_db()
        all_promises_result = db.query("""
            SELECT promise, deadline, source_url, status, evidence
            FROM promises WHERE person = %(person)s
            ORDER BY created_at ASC
        """, parameters={"person": person_name})
        
        all_promises_for_page = []
        for row in all_promises_result.result_rows:
            promise, deadline, source_url, status, evidence = row
            verdict_map = {
                "✅ Kept": "kept", "❌ Broken": "broken",
                "⚠️ Partial": "partial", "❓ Unclear": "unclear",
                "pending": "pending", "checking": "pending"
            }
            verdict_str = verdict_map.get(status, "pending")
            all_promises_for_page.append({
                "promise": promise,
                "deadline": deadline,
                "source_url": source_url,
                "verdict_data": {
                    "verdict": verdict_str,
                    "confidence": 0.8 if verdict_str not in ["pending"] else 0,
                    "summary": evidence if evidence else "Deadline not yet reached",
                    "evidence_url": source_url
                }
            })
    except Exception as e:
        print(f"  ⚠️ Could not load all promises: {e}")
        all_promises_for_page = promises_with_verdicts

    # Publish to GitHub Pages (public URL) + Senso knowledge base
    page_url = publish_to_github_pages(person_name, all_promises_for_page)
    publish_to_senso(person_name, all_promises_for_page)

    # Summary
    print(f"\n{'='*60}")
    print(f"🧾 RECEIPTS COMPLETE — {person_name}")
    print(f"{'='*60}")
    for item in promises_with_verdicts:
        v = item["verdict_data"]
        emoji = {"kept":"✅","broken":"❌","partial":"⚠️","unclear":"❓","pending":"⏳"}.get(v.get("verdict","⏳"),"⏳")
        print(f"{emoji} {item['promise'][:65]}")
        print(f"   Deadline: {item['deadline']}")
    if page_url:
        print(f"\n🔗 Published: {page_url}")
    print(f"{'='*60}\n")

    # Regenerate homepage
    try:
        from generate_homepage import generate_homepage
        generate_homepage()
    except Exception as e:
        print(f"  ⚠️ Homepage failed: {e}")

    return promises_with_verdicts

# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_table()
    person = input("Enter any public figure's name: ").strip()
    if not person:
        person = "Sam Altman"
    run_receipts(person)
