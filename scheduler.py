"""
RECEIPTS — Autonomous scheduler
Runs every 24 hours to check for new promises and update verdicts.
For demo: also supports --now flag to run immediately.
"""

import sys
import time
import schedule
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

# People to track automatically
TRACKED_PEOPLE = [
    "Sam Altman",
    "Elon Musk", 
    "Boris Johnson",
    "Donald Trump",
    "Narendra Modi",
    "Mark Zuckerberg",
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def daily_update():
    log("🔄 Starting autonomous update cycle...")
    
    try:
        from agent import run_receipts, setup_table
        setup_table()
        
        for person in TRACKED_PEOPLE:
            log(f"  → Checking {person}...")
            try:
                run_receipts(person)
            except Exception as e:
                log(f"  ⚠️ Failed for {person}: {e}")
        
        log("✅ All people updated")
        
    except Exception as e:
        log(f"❌ Update cycle failed: {e}")

def check_deadlines():
    """Check promises whose deadlines just passed and update verdicts."""
    log("⏰ Checking for newly expired deadlines...")
    
    try:
        from dotenv import load_dotenv
        import clickhouse_connect
        load_dotenv()
        
        db = clickhouse_connect.get_client(
            host=os.getenv("CLICKHOUSE_HOST"),
            port=int(os.getenv("CLICKHOUSE_PORT", 8443)),
            username=os.getenv("CLICKHOUSE_USER"),
            password=os.getenv("CLICKHOUSE_PASSWORD"),
            secure=True
        )
        
        # Find promises that are still pending but deadline has passed
        result = db.query("""
            SELECT person, promise, deadline
            FROM promises
            WHERE status = 'pending'
            AND toDate(created_at) < today()
            LIMIT 10
        """)
        
        if result.result_rows:
            log(f"  → Found {len(result.result_rows)} promises to re-check")
            from agent import check_verdict, update_verdict_in_db
            for row in result.result_rows:
                person, promise, deadline = row
                verdict = check_verdict(person, promise, deadline)
                update_verdict_in_db(person, promise, verdict, "")
                log(f"  → {person}: {verdict['verdict']}")
        else:
            log("  → No newly expired deadlines")
            
    except Exception as e:
        log(f"  ⚠️ Deadline check failed: {e}")

def rebuild():
    """Rebuild all pages and homepage."""
    try:
        from rebuild_pages import rebuild_all
        from generate_homepage import generate_homepage
        rebuild_all()
        generate_homepage()
        log("✅ Pages rebuilt and pushed")
    except Exception as e:
        log(f"⚠️ Rebuild failed: {e}")

def full_cycle():
    """Complete autonomous cycle."""
    log("="*50)
    log("🤖 RECEIPTS AUTONOMOUS CYCLE STARTING")
    log("="*50)
    daily_update()
    check_deadlines()
    rebuild()
    log("="*50)
    log(f"✅ CYCLE COMPLETE — next run in 24 hours")
    log("="*50)

if __name__ == "__main__":
    # --now flag runs immediately (good for demo)
    if "--now" in sys.argv:
        log("🚀 Running immediate update cycle...")
        full_cycle()
        sys.exit(0)
    
    # --demo flag runs every 5 minutes (good for showing during demo)
    if "--demo" in sys.argv:
        log("🎬 Demo mode: running every 5 minutes")
        log(f"Tracking: {', '.join(TRACKED_PEOPLE)}")
        schedule.every(5).minutes.do(full_cycle)
        full_cycle()  # Run immediately first
        while True:
            schedule.run_pending()
            time.sleep(10)
    
    # Default: run every 24 hours
    log("🕐 Receipts autonomous scheduler starting...")
    log(f"Tracking {len(TRACKED_PEOPLE)} people")
    log(f"Next update: in 24 hours")
    log(f"Tracked: {', '.join(TRACKED_PEOPLE)}")
    
    schedule.every(24).hours.do(full_cycle)
    
    # Run once immediately on startup
    full_cycle()
    
    while True:
        schedule.run_pending()
        time.sleep(60)
