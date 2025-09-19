import streamlit as st
import os, tempfile, pandas as pd, numpy as np, shutil, validators, json
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load API
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY not found in .env file.")
    st.stop()
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# UI
st.title("🚀 GitHub Repository Code Analyzer (Optimized)")
repo_urls = st.text_area("🔗 Enter GitHub Repo URLs (comma-separated):")

# --- PDF Report ---
def generate_pdf_report(report_data, overall_score, repo_summary, pdf_path, repo_name):
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(100, height - 50, f"Repo Code Analysis - {repo_name}")
    c.setFont("Helvetica", 12)
    c.drawString(100, height - 70, f"Overall Score: {overall_score:.2f}%")
    c.drawString(100, height - 90, f"Verdict: {repo_summary.get('verdict')}")

    # Summary
    wrapped = simpleSplit("Summary: " + repo_summary.get("summary", ""), "Helvetica", 10, width - 100)
    y = height - 120
    for line in wrapped:
        c.drawString(70, y, line)
        y -= 15

    # Table
    y -= 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "File Name")
    c.drawString(250, y, "Score")
    c.drawString(350, y, "Issues & Recs")
    y -= 20

    c.setFont("Helvetica", 9)
    for entry in report_data:
        file_name, score, issues, recs = entry.get("file_name","?"), entry.get("overall_score","N/A"), entry.get("key_issues",[]), entry.get("recommendations",[])
        if y < 50: c.showPage(); y = height - 50
        c.drawString(50,y,str(file_name)); c.drawString(250,y,str(score)); y-=15
        for line in simpleSplit("Issues: " + ", ".join(issues), "Helvetica", 9, width - 100):
            c.drawString(70,y,line); y-=12
        for line in simpleSplit("Recs: " + ", ".join(recs), "Helvetica", 9, width - 100):
            c.drawString(70,y,line); y-=12
        y-=10
    c.showPage(); c.save()

# --- File Analyzer ---
def analyze_code_file(file_path):
    try:
        with open(file_path,"r",encoding="utf-8",errors="ignore") as f:
            code = f.read()
        # Limit code size
        code = code[:1500]  
        prompt = f"""
        Analyze this code and return JSON:
        {{
          "file_name":"{os.path.basename(file_path)}",
          "correctness_score":int,
          "efficiency_score":int,
          "best_practices_score":int,
          "overall_score":int,
          "key_issues":["..."],
          "recommendations":["..."]
        }}
        Code:\n{code}
        """
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        return {"file_name":os.path.basename(file_path),"overall_score":None,"key_issues":[f"Error:{e}"],"recommendations":[]}

# --- Repo Summary ---
def analyze_repo_summary(report_data):
    try:
        compact = [{ "file_name": r["file_name"], "overall_score": r.get("overall_score") } for r in report_data]
        prompt = f"""
        Based on these file scores: {json.dumps(compact)},
        return JSON {{"verdict":"Good|Moderate|Poor","summary":"short overall review"}}
        """
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except:
        return {"verdict":"Unknown","summary":"Could not summarize."}

# --- Repo Analyzer ---
def analyze_repo(repo_url):
    try:
        temp_dir = tempfile.mkdtemp()
        repo_name = repo_url.split("/")[-1].replace(".git","")
        repo_path = os.path.join(temp_dir,repo_name)
        os.system(f"git clone --depth 1 {repo_url} {repo_path}")

        files = []
        for root,_,fs in os.walk(repo_path):
            for f in fs:
                if f.endswith((".py",".js",".java",".cpp",".ts")):
                    files.append(os.path.join(root,f))

        # Parallel file analysis
        report_data, scores = [], []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(analyze_code_file,f): f for f in files}
            for fut in as_completed(futures):
                result = fut.result()
                report_data.append(result)
                if result.get("overall_score") is not None:
                    scores.append(result["overall_score"])

        overall_score = np.mean(scores) if scores else 0
        repo_summary = analyze_repo_summary(report_data)

        st.success(f"✅ Done for {repo_url}")
        st.write(f"**Overall Score:** {overall_score:.2f}% | **Verdict:** {repo_summary['verdict']}")
        st.write(f"**Summary:** {repo_summary['summary']}")
        st.dataframe(pd.DataFrame(report_data))

        pdf_path = os.path.join(temp_dir,f"{repo_name}_report.pdf")
        generate_pdf_report(report_data,overall_score,repo_summary,pdf_path,repo_name)
        with open(pdf_path,"rb") as f:
            st.download_button(f"📥 Download {repo_name} Report",f,file_name=f"{repo_name}_report.pdf")
        shutil.rmtree(temp_dir)
    except Exception as e:
        st.error(f"Error analyzing {repo_url}: {e}")

# --- Button Handler ---
if st.button("Analyze Repositories"):
    urls=[u.strip() for u in repo_urls.split(",") if u.strip()]
    valid=[u for u in urls if validators.url(u) and "github.com" in u]
    if valid:
        with st.spinner(f"Analyzing {len(valid)} repos..."):
            for u in valid: analyze_repo(u)
    else:
        st.error("Invalid GitHub URLs")
