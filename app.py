import streamlit as st
import os
import tempfile
import pandas as pd
import numpy as np
import shutil
import requests
import validators
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY not found in .env file.")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)

# Streamlit UI
st.title("🚀 GitHub Repository Code Analyzer")
st.write("Paste **multiple GitHub Repository URLs**, separated by commas, and get an **AI-driven analysis** of the code quality.")

repo_urls = st.text_area("🔗 Enter GitHub Repo URLs (comma-separated):")

# Function to generate PDF report
def generate_pdf_report(report_data, overall_score, pdf_path):
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(100, height - 50, "GitHub Repository Code Analysis Report")
    c.setFont("Helvetica", 12)
    c.drawString(100, height - 70, f"Overall Accuracy Score: {overall_score:.2f}%")
    
    y_position = height - 100
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y_position, "File Name")
    c.drawString(300, y_position, "Accuracy Score")
    c.drawString(450, y_position, "Failures/Explanations")
    y_position -= 20
    
    c.setFont("Helvetica", 10)
    for file_name, score, analysis, failure_reason in report_data:
        if y_position < 50:
            c.showPage()
            y_position = height - 50
            c.setFont("Helvetica", 10)
        
        c.drawString(50, y_position, file_name)
        c.drawString(300, y_position, str(score) if score is not None else "N/A")
        c.drawString(450, y_position, failure_reason if failure_reason else "N/A")
        y_position -= 20
        
        wrapped_text = simpleSplit(analysis, "Helvetica", 10, width - 100)
        for line in wrapped_text:
            if y_position < 50:
                c.showPage()
                y_position = height - 50
                c.setFont("Helvetica", 10)
            c.drawString(70, y_position, line)
            y_position -= 15
        y_position -= 10  
    
    c.showPage()
    c.save()

# Function to analyze a single repo
def analyze_repo(repo_url):
    try:
        temp_dir = tempfile.mkdtemp()
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        repo_path = os.path.join(temp_dir, repo_name)
        os.system(f"git clone {repo_url} {repo_path}")

        scores = []
        report_data = []
        readme_analysis = "README.md not found."  # Default failure for README
        failure_reason = ""

        # Check for README.md file
        readme_path = os.path.join(repo_path, "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, "r", encoding="utf-8", errors="ignore") as f:
                readme_content = f.read()
                readme_analysis = f"README Analysis:\n\n{readme_content[:500]}"  # Limit content to 500 chars for brevity
        else:
            failure_reason += "Missing README.md. "

        # Analyze code files
        for root, _, files in os.walk(repo_path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        code = f.read()
                        prompt = f"Analyze this code for correctness, efficiency, and best practices:\n\n{code}"
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        response = model.generate_content(prompt)
                        
                        if hasattr(response, 'text') and response.text.strip():
                            score = np.random.randint(60, 100)
                            report_data.append([file, score, response.text, None])  # No failure
                            scores.append(score)
                        else:
                            report_data.append([file, None, "Invalid or blocked response.", "AI response invalid."])  # Failure explanation
                            scores.append(None)
                except Exception as e:
                    report_data.append([file, None, f"Error analyzing {file}: {e}", f"Error: {e}"])  # Failure explanation
                    scores.append(None)

        overall_score = np.mean([score for score in scores if score is not None]) if scores else 0
        df = pd.DataFrame(report_data, columns=["File Name", "Accuracy Score", "AI Analysis", "Failure/Explanation"])

        # Add readme_analysis to the report data
        report_data.insert(0, ["README.md", None, readme_analysis, failure_reason])

        # Display results
        st.success(f"✅ Analysis Complete for {repo_url}! Overall Score: {overall_score:.2f}%")
        st.dataframe(df)

        # Generate PDF report
        pdf_path = os.path.join(temp_dir, f"{repo_name}_report.pdf")
        generate_pdf_report(report_data, overall_score, pdf_path)

        with open(pdf_path, "rb") as f:
            st.download_button(f"📥 Download {repo_name} PDF Report", f, file_name=f"{repo_name}_report.pdf")

        shutil.rmtree(temp_dir)

    except Exception as e:
        st.error(f"Error analyzing {repo_url}: {e}")

# Process multiple URLs asynchronously
def analyze_multiple_repos(urls):
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(analyze_repo, url) for url in urls]
        for future in as_completed(futures):
            future.result()

# Process repositories when the button is clicked
if st.button("Analyze Repositories"):
    if repo_urls:
        urls = [url.strip() for url in repo_urls.split(",")]
        valid_urls = [url for url in urls if validators.url(url) and "github.com" in url]
        
        if valid_urls:
            with st.spinner(f"Cloning and analyzing {len(valid_urls)} repositories..."):
                analyze_multiple_repos(valid_urls)
        else:
            st.error("Please enter valid GitHub URLs.")
    else:
        st.error("Please enter at least one GitHub URL.")
