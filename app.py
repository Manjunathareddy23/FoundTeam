import streamlit as st
import os
import tempfile
import pandas as pd
import numpy as np
import shutil
import validators
import json
import re
import subprocess
import time
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------- config ----------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY not found in .env file.")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# UI
st.title("🚀 GitHub Repository Code Analyzer (Fixed & Hardened)")
st.write("Paste **multiple GitHub Repo URLs**, separated by commas, and get an **AI-driven analysis** of the code quality.")
repo_urls = st.text_area("🔗 Enter GitHub Repo URLs (comma-separated):")

# ---------- helpers ----------
def safe_clone(repo_url, dest):
    """Shallow clone, return (ok, msg)"""
    try:
        cmd = ["git", "clone", "--depth", "1", "--quiet", repo_url, dest]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return False, proc.stderr.strip() or proc.stdout.strip()
        return True, "Cloned"
    except Exception as e:
        return False, str(e)

def safe_generate(prompt, timeout_sec=30):
    """Call Gemini and return text or None. Handles several response shapes."""
    try:
        resp = model.generate_content(prompt)
    except Exception as e:
        # model call failed
        return None

    # try several ways to extract text
    try:
        if hasattr(resp, "text") and isinstance(resp.text, str):
            return resp.text
    except Exception:
        pass

    try:
        if hasattr(resp, "candidates") and resp.candidates:
            # candidates may contain content fields
            cand = resp.candidates[0]
            # different client shapes: cand.content may be str or list of dicts
            if hasattr(cand, "content"):
                content = cand.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for p in content:
                        if isinstance(p, dict) and p.get("text"):
                            parts.append(p["text"])
                        elif hasattr(p, "text"):
                            parts.append(p.text)
                    if parts:
                        return "".join(parts)
    except Exception:
        pass

    # last fallback
    try:
        return str(resp)
    except Exception:
        return None

def extract_json_from_text(text):
    """Try to find the first balanced {...} JSON object and parse it."""
    if not text or not isinstance(text, str):
        return None
    # try fenced ```json ... ``` first
    m = re.search(r"```json(.*?)```", text, re.S | re.I)
    if m:
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # find first balanced {...}
    starts = [m.start() for m in re.finditer(r"\{", text)]
    for s in starts:
        depth = 0
        for i in range(s, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[s:i+1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
    # fallback: try to extract something that looks like JSON with regex
    try:
        return json.loads(text.strip())
    except Exception:
        return None

def heuristic_analyze(code, file_name):
    """Fallback heuristic analysis when AI fails. Returns full result dict."""
    lines = code.splitlines()
    nlines = len(lines)
    text = code.lower()

    # base scores
    base = 70
    if "todo" in text or "pass" in text or "notimplementederror" in text:
        base -= 20
    if "print(" in text and "logging" not in text:
        base -= 5
    if nlines > 500:
        base -= 10
    if re.search(r"\bfor\s+.*:\s*\n\s*for\s+", code):
        base -= 15  # nested loops potential inefficiency
    if "import unittest" in text or "pytest" in text:
        base += 5

    base = max(10, min(95, base))

    correctness_score = max(5, min(100, int(base - 5)))
    efficiency_score = max(5, min(100, int(base - (10 if re.search(r"\bfor\s+.*:\s*\n\s*for\s+", code) else 5))))
    best_practices_score = max(5, min(100, int(base + (5 if '"""' in code or "''' " in code or "def " in code else 0))))

    overall_score = int(round((correctness_score + efficiency_score + best_practices_score) / 3.0))

    issues = []
    recs = []
    if "todo" in text:
        issues.append("TODO markers left")
        recs.append("Resolve TODOs and implement missing functionality")
    if "pass" in text or "notimplementederror" in text:
        issues.append("Empty function(s) or NotImplemented")
        recs.append("Implement function bodies")
    if re.search(r"\bfor\s+.*:\s*\n\s*for\s+", code):
        issues.append("Nested loops (possible inefficiency)")
        recs.append("Consider algorithmic optimizations or use vectorized operations")
    if "print(" in text and "logging" not in text:
        issues.append("Direct print statements (not logger)")
        recs.append("Use logging module for production code")

    if not issues:
        issues = ["No obvious issues found by heuristic"]
        recs = ["Run tests and unit tests to confirm correctness"]

    return {
        "file_name": os.path.basename(file_name),
        "correctness_score": correctness_score,
        "efficiency_score": efficiency_score,
        "best_practices_score": best_practices_score,
        "overall_score": overall_score,
        "key_issues": issues,
        "recommendations": recs,
        "analysis_source": "heuristic"
    }

# ---------- AI-backed file analysis ----------
def analyze_code_file(file_path, max_chars=2000):
    """Try AI analysis, fall back to heuristic if AI output unusable."""
    try:
        # skip huge/binary files
        try:
            size = os.path.getsize(file_path)
            if size > 500 * 1024:  # > 500KB
                return {
                    "file_name": os.path.basename(file_path),
                    "overall_score": None,
                    "key_issues": ["File too large to analyze"],
                    "recommendations": ["Analyze large files locally or increase limit"],
                    "analysis_source": "skipped"
                }
        except Exception:
            pass

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()

        code_snippet = code[:max_chars]

        prompt = f"""
You are an AI code reviewer. Return ONLY valid JSON (no surrounding text). JSON format must be:
{{
  "file_name": "{os.path.basename(file_path)}",
  "correctness_score": <int 0-100>,
  "efficiency_score": <int 0-100>,
  "best_practices_score": <int 0-100>,
  "overall_score": <int 0-100>,
  "key_issues": ["..."],
  "recommendations": ["..."]
}}

Analyze this code (first {max_chars} characters shown). If you cannot produce JSON, return nothing.
Code (truncated):
\"\"\"{code_snippet}\"\"\"
"""
        # call model
        ai_text = safe_generate(prompt)
        if ai_text:
            parsed = extract_json_from_text(ai_text)
            if parsed and isinstance(parsed, dict):
                # ensure expected keys exist, fill defaults if necessary
                for k in ["file_name", "correctness_score", "efficiency_score", "best_practices_score", "overall_score", "key_issues", "recommendations"]:
                    if k not in parsed:
                        parsed[k] = None if k.endswith("_score") else []
                parsed["analysis_source"] = "ai"
                return parsed

        # fallback heuristic
        return heuristic_analyze(code, file_path)

    except Exception as e:
        # error => fallback
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()
            return heuristic_analyze(code, file_path)
        except Exception:
            return {
                "file_name": os.path.basename(file_path),
                "overall_score": None,
                "key_issues": [f"Error analyzing file: {e}"],
                "recommendations": []
            }

# ---------- repo summary ----------
def make_repo_summary(report_data):
    """Try AI summary; if fails create deterministic summary."""
    # compact info to send to AI: only file_name and overall_score
    compact = [{"file_name": r.get("file_name"), "overall_score": r.get("overall_score")} for r in report_data]
    prompt = f"""
Based on this list of per-file analysis results (JSON array), return ONLY JSON:
{{"verdict": "<Good|Moderate|Poor>", "summary": "<one-paragraph summary>" }}

File results:
{json.dumps(compact, indent=2)}
"""
    ai_text = safe_generate(prompt)
    if ai_text:
        parsed = extract_json_from_text(ai_text)
        if parsed and "verdict" in parsed and "summary" in parsed:
            return parsed

    # deterministic fallback
    scores = [r.get("overall_score") for r in report_data if isinstance(r.get("overall_score"), (int, float))]
    avg = float(np.mean(scores)) if scores else 0.0
    low_count = sum(1 for s in scores if s < 50)
    total_files = len(report_data)
    if avg >= 80:
        verdict = "Good"
    elif avg >= 50:
        verdict = "Moderate"
    else:
        verdict = "Poor"

    summary = f"Average file score {avg:.1f}%. {low_count}/{total_files} file(s) scored below 50%. "
    if low_count > 0:
        summary += "Recommend fixing issues in low-scoring files and adding tests."
    else:
        summary += "Repository appears generally healthy; run full test suite to confirm."

    return {"verdict": verdict, "summary": summary}

# ---------- PDF report ----------
def generate_pdf_report(report_data, overall_score, repo_summary, pdf_path, repo_name):
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60, height - 50, f"GitHub Repository Code Analysis Report - {repo_name}")
    c.setFont("Helvetica", 11)
    c.drawString(60, height - 70, f"Overall Repository Score: {overall_score:.2f}%")
    c.drawString(60, height - 88, f"Verdict: {repo_summary.get('verdict')}")
    wrapped = simpleSplit("Summary: " + repo_summary.get("summary", ""), "Helvetica", 10, width - 120)
    y = height - 110
    for line in wrapped:
        c.drawString(70, y, line)
        y -= 14
    y -= 8
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "File Name")
    c.drawString(260, y, "Score")
    c.drawString(330, y, "Source")
    c.drawString(400, y, "Issues / Recs (truncated)")
    y -= 18
    c.setFont("Helvetica", 9)
    for entry in report_data:
        if y < 60:
            c.showPage()
            y = height - 50
        fname = str(entry.get("file_name", ""))
        score = str(entry.get("overall_score", "N/A"))
        src = entry.get("analysis_source", "")
        issues = ", ".join(entry.get("key_issues", [])[:3])
        recs = ", ".join(entry.get("recommendations", [])[:3])
        line = f"{issues} | {recs}"
        c.drawString(50, y, fname[:36])
        c.drawString(260, y, score)
        c.drawString(330, y, src)
        wrapped_lr = simpleSplit(line, "Helvetica", 8, width - 420)
        for part in wrapped_lr:
            c.drawString(400, y, part)
            y -= 12
        y -= 6
    c.showPage()
    c.save()

# ---------- main analyzer ----------
def analyze_repo(repo_url, show_progress=True):
    temp_dir = tempfile.mkdtemp(prefix="repo_")
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    dest = os.path.join(temp_dir, repo_name)
    ok, msg = safe_clone(repo_url, dest)
    if not ok:
        shutil.rmtree(temp_dir, ignore_errors=True)
        st.error(f"Failed to clone {repo_url}: {msg}")
        return None

    if show_progress:
        st.info(f"Cloned {repo_name} → analyzing files...")

    # gather candidate files
    candidate_files = []
    for root, _, files in os.walk(dest):
        for f in files:
            # skip common binaries/build artifacts
            if f.endswith((".py", ".js", ".java", ".cpp", ".c", ".h", ".ts", ".go", ".rb")):
                candidate_files.append(os.path.join(root, f))

    # analyze in parallel, but bound workers
    report_data = []
    scores = []
    max_workers = min(4, max(1, len(candidate_files)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(analyze_code_file, path): path for path in candidate_files}
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as e:
                res = {
                    "file_name": os.path.basename(futures[fut]),
                    "overall_score": None,
                    "key_issues": [f"Unhandled error: {e}"],
                    "recommendations": [],
                    "analysis_source": "error"
                }
            report_data.append(res)
            if isinstance(res.get("overall_score"), (int, float)):
                scores.append(float(res["overall_score"]))

    overall_score = float(np.mean(scores)) if scores else 0.0
    repo_summary = make_repo_summary(report_data)

    # UI output
    st.success(f"✅ Done for {repo_url}")
    st.write(f"**Overall Score:** {overall_score:.2f}%")
    st.write(f"**Verdict:** {repo_summary.get('verdict')}")
    st.write(f"**Summary:** {repo_summary.get('summary')}")
    if report_data:
        df = pd.DataFrame(report_data)
        st.dataframe(df[["file_name", "analysis_source", "overall_score", "key_issues", "recommendations"]])

    # PDF
    pdf_path = os.path.join(temp_dir, f"{repo_name}_report.pdf")
    generate_pdf_report(report_data, overall_score, repo_summary, pdf_path, repo_name)
    with open(pdf_path, "rb") as f:
        st.download_button(f"📥 Download PDF Report", f, file_name=f"{repo_name}_report.pdf")

    shutil.rmtree(temp_dir, ignore_errors=True)
    return {"repo": repo_name, "score": overall_score, "summary": repo_summary, "files": len(report_data)}

# ---------- handler ----------
if st.button("Analyze Repositories"):
    if not repo_urls.strip():
        st.error("Please enter at least one GitHub URL.")
    else:
        urls = [u.strip() for u in repo_urls.split(",") if u.strip()]
        valid_urls = [u for u in urls if validators.url(u) and "github.com" in u]
        if not valid_urls:
            st.error("Please enter valid GitHub URLs (github.com).")
        else:
            with st.spinner("Cloning and analyzing repositories..."):
                for url in valid_urls:
                    analyze_repo(url)
