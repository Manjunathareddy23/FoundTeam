import streamlit as st
import os
import tempfile
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from pygments.lexers import get_lexer_for_filename
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
import validators
import requests
import shutil

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Check if the environment variable is loaded correctly
if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY not found in .env file.")
    st.stop()

# Initialize AI API
import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)

# Tailwind CSS for UI Styling
st.markdown("""
    <style>
        body {background-color: #f8fafc; font-family: 'Arial', sans-serif;}
        .main {background-color: white; border-radius: 12px; padding: 20px; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);}
        .stButton > button {background-color: #4f46e5; color: white; padding: 10px; border-radius: 8px;}
    </style>
""", unsafe_allow_html=True)

st.title("🚀 GitHub Repository Code Analyzer")
st.write("Paste a **GitHub Repository URL**, and get an **AI-driven analysis** of the code quality.")

# User Input
repo_url = st.text_input("🔗 Enter GitHub Repo URL:")

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
    y_position -= 20
    
    c.setFont("Helvetica", 10)
    for file_name, score, analysis in report_data:
        if y_position < 50:  # Check if a new page is needed
            c.showPage()
            y_position = height - 50
            c.setFont("Helvetica", 10)
        
        c.drawString(50, y_position, file_name)
        c.drawString(300, y_position, str(score) if score is not None else "N/A")
        y_position -= 20
        
        wrapped_text = simpleSplit(analysis, "Helvetica", 10, width - 100)
        for line in wrapped_text:
            if y_position < 50:
                c.showPage()
                y_position = height - 50
                c.setFont("Helvetica", 10)
            c.drawString(70, y_position, line)
            y_position -= 15
        y_position -= 10  # Extra spacing between analyses
    
    c.showPage()
    c.save()

if st.button("Analyze Repository"):
    if validators.url(repo_url) and "github.com" in repo_url:
        with st.spinner("Cloning repository..."):
            # Create a temporary directory
            temp_dir = tempfile.mkdtemp()
            repo_name = repo_url.split('/')[-1].replace('.git', '')
            repo_path = os.path.join(temp_dir, repo_name)
            
            # Use system command to clone the repository
            os.system(f"git clone {repo_url} {repo_path}")
            
            # Analyze Code Files
            scores = []
            report_data = []
            
            for root, _, files in os.walk(repo_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            code = f.read()
                            
                            prompt = f"Analyze this code for correctness, efficiency, and best practices:\n\n{code}"
                            model = genai.GenerativeModel("gemini-1.5-flash")
                            response = model.generate_content(prompt)
                            
                            # Check if response contains valid content
                            if hasattr(response, 'text') and response.text.strip():
                                score = np.random.randint(60, 100)  # Mock Score for simplicity
                                report_data.append([file, score, response.text])
                                scores.append(score)
                            else:
                                st.warning(f"Skipping {file} due to invalid response or copyrighted content.")
                                report_data.append([file, None, "Invalid or blocked response due to copyrighted content."])
                                scores.append(None)
                    except Exception as e:
                        st.error(f"Error analyzing {file}: {e}")
            
            # Calculate overall score
            overall_score = np.mean([score for score in scores if score is not None]) if scores else 0
            
            # Convert to DataFrame
            df = pd.DataFrame(report_data, columns=["File Name", "Accuracy Score", "AI Analysis"])
            st.success(f"✅ Analysis Complete! Overall Score: {overall_score:.2f}%")
            st.dataframe(df)
            
            # Generate PDF Report
            pdf_path = os.path.join(temp_dir, "report.pdf")
            generate_pdf_report(report_data, overall_score, pdf_path)
            
            # Provide Download Links
            with open(pdf_path, "rb") as f:
                st.download_button("📥 Download PDF Report", f, file_name="report.pdf")
            
            # Clean Up
            shutil.rmtree(temp_dir)
    else:
        st.error("Invalid GitHub URL. Please enter a valid repository link.")
