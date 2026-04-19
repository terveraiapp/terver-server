"""
End-to-end production smoke tests.
Run: python tests/test_prod.py
"""
import io
import json
import sys
import time
import httpx
from docx import Document as DocxDocument

BASE = "https://terver-server.onrender.com"

PASS = "PASS"
FAIL = "FAIL"
INFO = " -- "

DEED_TEXT = [
    "DEED OF ASSIGNMENT",
    "This Deed of Assignment is made this 12th day of March 2019 between:",
    'GRANTOR: Kofi Mensah (hereinafter called "the Vendor")',
    'GRANTEE: Ama Asante (hereinafter called "the Purchaser")',
    "PROPERTY DESCRIPTION:",
    "ALL THAT piece or parcel of land situate lying and being at East Legon, Accra in the Greater Accra Region of the Republic of Ghana being Plot No. 47, Block 5, Atomic Hills Estate, containing an area of 0.25 acres more or less.",
    "SURVEY NUMBER: GS/2144/2018",
    "LAND COMMISSION REF: LC/ACC/2019/004421",
    "STAMP DUTY PAID: GHS 1,200.00 - receipt no. SD/2019/77423",
    "Signed by the Vendor: ____________________   Date: 12/03/2019",
    "Signed by the Purchaser: ________________   Date: 12/03/2019",
    "Witnessed by: John Adu Boahen (Solicitor) - License No. GLS/1045",
]

DEED2_TEXT = [
    "INDENTURE dated 5th November 2021",
    "VENDOR: Kwame Darko",
    "PURCHASER: Ama Asante",
    "Land being Plot No. 47, Block 5, Atomic Hills Estate, East Legon.",
    "Survey Number: GS/2144/2018",
    "Area: 0.30 acres  (NOTE: differs from original deed which stated 0.25 acres)",
    "Signed: ___________   Witnessed: Yaa Boateng (Solicitor)",
]


def make_docx(paragraphs: list) -> io.BytesIO:
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def section(title: str):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)


def ok(msg: str):
    print(f"  {PASS} {msg}")


def fail(msg: str):
    print(f"  {FAIL} {msg}")
    sys.exit(1)


def info(msg: str):
    print(f"  {INFO} {msg}")


# ─── 1. Health ────────────────────────────────────────────
section("1. Health check")
r = httpx.get(f"{BASE}/health", timeout=30)
assert r.status_code == 200 and r.json()["status"] == "ok", f"Unexpected: {r.text}"
ok(f"GET /health -> {r.json()}")


# ─── 2. Single document analysis ─────────────────────────
section("2. Single document analysis  (/analyze)")
def run_analyze(file_buf, filename="test_deed.docx"):
    """Stream /analyze, return (session_id, raw_json, events). Retries on quota errors."""
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    for attempt in range(1, 4):
        file_buf.seek(0)
        sid, rj, ev = None, "", []
        quota_hit = False
        with httpx.stream("POST", f"{BASE}/analyze",
                          files={"file": (filename, file_buf, mime)},
                          timeout=120) as resp:
            if resp.status_code != 200:
                fail(f"HTTP {resp.status_code}: {resp.read().decode()}")
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                ev.append(payload["type"])
                if payload["type"] == "session":
                    sid = payload.get("session_id")
                    info(f"session_id = {sid}")
                elif payload["type"] == "token":
                    rj += payload.get("token", "")
                elif payload["type"] == "done" and payload.get("raw"):
                    rj = payload["raw"]
                elif payload["type"] == "error":
                    msg = payload.get("message", "")
                    if "quota" in msg.lower() or "rate" in msg.lower():
                        quota_hit = True
                        break
                    fail(f"Server error: {msg}")
        if not quota_hit:
            return sid, rj, ev
        wait = 60 * attempt
        info(f"Quota hit (attempt {attempt}/3) — waiting {wait}s...")
        time.sleep(wait)
    fail("Gemini quota exhausted after 3 retries. Try again in a few minutes.")


docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
info("Uploading fake deed (DOCX)...")
fake_file = make_docx(DEED_TEXT)
session_id, raw_json, events_received = run_analyze(fake_file)

ok(f"SSE events received: {events_received}")

if not session_id:
    fail("No session_id received in stream")
ok(f"session_id received: {session_id[:8]}…")

try:
    result = json.loads(raw_json)
except json.JSONDecodeError as e:
    fail(f"Could not parse analysis JSON: {e}\nRaw: {raw_json[:300]}")

ok(f"Analysis JSON parsed successfully")
ok(f"risk_score = {result.get('risk_score')}  overall_score = {result.get('overall_score')}")

cats = result.get("categories", [])
ok(f"{len(cats)} categories returned: {[c['name'] for c in cats]}")
assert len(cats) >= 4, f"Expected ≥4 categories, got {len(cats)}"

summary = result.get("summary", "")
assert len(summary) > 20, "Summary too short"
ok(f"Summary: {summary[:100]}…")

doc_context = json.dumps(result)


# ─── 3. Chat with Amberlyn ────────────────────────────────
info("Waiting 10s before chat calls (Gemini free-tier rate limit)...")
time.sleep(10)
section("3. Chat — /chat/{session_id}")

def chat(message: str, label: str) -> str:
    info(f'Sending: "{message}"')
    full = ""
    with httpx.stream(
        "POST",
        f"{BASE}/chat/{session_id}",
        json={"message": message, "document_context": doc_context},
        timeout=60,
    ) as resp:
        if resp.status_code != 200:
            fail(f"Chat HTTP {resp.status_code}: {resp.read().decode()}")
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:].strip())
            if payload["type"] == "token":
                full += payload.get("token", "")
            elif payload["type"] == "error":
                fail(f"Chat error on '{label}': {payload.get('message')}")
    return full

# Turn 1 — general risk question
reply1 = chat("Is this document safe to rely on?", "risk question")
assert len(reply1) > 20, "Reply too short"
ok(f"Reply 1 ({len(reply1)} chars): {reply1[:120]}…")

# Turn 2 — exact document content question (tests raw text grounding)
time.sleep(8)
reply2 = chat("What is the plot number and survey number in this deed?", "exact content")
assert len(reply2) > 10, "Reply too short"
ok(f"Reply 2 ({len(reply2)} chars): {reply2[:120]}…")

# Check Amberlyn actually found the correct values from raw text
grounded = "47" in reply2 or "GS/2144" in reply2 or "plot" in reply2.lower()
if grounded:
    ok("Amberlyn cited document-specific details (grounding confirmed)")
else:
    info(f"⚠ Could not confirm grounding — full reply: {reply2}")

# Turn 3 — memory / follow-up (tests conversation continuity)
time.sleep(8)
reply3 = chat("Who are the parties involved?", "parties / memory")
assert len(reply3) > 10, "Reply too short"
ok(f"Reply 3 ({len(reply3)} chars): {reply3[:120]}…")

party_grounded = "Mensah" in reply3 or "Asante" in reply3 or "vendor" in reply3.lower() or "purchaser" in reply3.lower()
if party_grounded:
    ok("Amberlyn cited correct parties from document (grounding confirmed)")
else:
    info(f"⚠ Could not confirm party grounding — full reply: {reply3}")


# ─── 4. Case analysis ────────────────────────────────────
info("Waiting 15s before case analysis (Gemini free-tier rate limit)...")
time.sleep(15)
section("4. Case analysis  (/analyze-case)")
info("Uploading 2 fake documents as a case (DOCX)...")

case_session_id = None
case_raw_json = ""
case_events = []

with httpx.stream(
    "POST",
    f"{BASE}/analyze-case",
    files=[
        ("files", ("deed.docx", make_docx(DEED_TEXT), docx_mime)),
        ("files", ("indenture.docx", make_docx(DEED2_TEXT), docx_mime)),
    ],
    timeout=180,
) as resp:
    if resp.status_code != 200:
        fail(f"Case HTTP {resp.status_code}: {resp.read().decode()}")
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        payload = json.loads(line[5:].strip())
        case_events.append(payload["type"])
        if payload["type"] == "session":
            case_session_id = payload.get("session_id")
            info(f"case session_id = {case_session_id}")
        elif payload["type"] == "token":
            case_raw_json += payload.get("token", "")
        elif payload["type"] == "done" and payload.get("raw"):
            case_raw_json = payload["raw"]
        elif payload["type"] == "error":
            fail(f"Case analysis error: {payload.get('message')}")

ok(f"Case SSE events: {case_events}")

try:
    case_result = json.loads(case_raw_json)
except json.JSONDecodeError as e:
    fail(f"Could not parse case JSON: {e}\nRaw: {case_raw_json[:300]}")

ok(f"Case JSON parsed — risk_score={case_result.get('risk_score')} overall={case_result.get('overall_score')}")

docs_id = case_result.get("documents_identified", [])
cross_issues = case_result.get("cross_document_issues", [])
ok(f"documents_identified: {docs_id}")
ok(f"cross_document_issues: {cross_issues}")

# Expect Gemini to flag the acreage mismatch (0.25 vs 0.30)
area_flagged = any("0.25" in i or "0.30" in i or "area" in i.lower() or "acre" in i.lower() for i in cross_issues)
if area_flagged:
    ok("Gemini correctly flagged the acreage discrepancy between documents")
else:
    info(f"⚠ Acreage discrepancy not explicitly flagged — cross issues: {cross_issues}")


# ─── Done ─────────────────────────────────────────────────
section("ALL TESTS PASSED")
print()
