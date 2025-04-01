import streamlit as st
import google.generativeai as genai
import validators
import requests
import git
import shutil
import os
import tempfile
import pandas as pd
import numpy as np
from pygments.lexers import get_lexer_for_filename
from reportlab.pdfgen import canvas
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

if st.button("Analyze Repository"):
    if validators.url(repo_url) and "github.com" in repo_url:
        with st.spinner("Cloning repository..."):
            temp_dir = tempfile.mkdtemp()
            repo_name = repo_url.split('/')[-1].replace('.git', '')
            repo_path = os.path.join(temp_dir, repo_name)
            git.Repo.clone_from(repo_url, repo_path)
            
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
                            score = np.random.randint(60, 100)  # Mock Score for simplicity
                            
                            report_data.append([file, score, response.text])
                            scores.append(score)
                    except Exception as e:
                        st.error(f"Error analyzing {file}: {e}")
            
            # Calculate overall score
            overall_score = np.mean(scores) if scores else 0
            
            # Convert to DataFrame
            df = pd.DataFrame(report_data, columns=["File Name", "Accuracy Score", "AI Analysis"])
            st.success(f"✅ Analysis Complete! Overall Score: {overall_score:.2f}%")
            st.dataframe(df)
            
            # Generate PDF Report
            pdf_path = os.path.join(temp_dir, "report.pdf")
            c = canvas.Canvas(pdf_path)
            c.drawString(100, 800, "GitHub Repository Code Analysis Report")
            c.drawString(100, 780, f"Overall Accuracy Score: {overall_score:.2f}%")
            c.showPage()
            c.save()
            
            # Provide Download Links
            with open(pdf_path, "rb") as f:
                st.download_button("📥 Download PDF Report", f, file_name="report.pdf")
            
            # Clean Up
            shutil.rmtree(temp_dir)
    else:
        st.error("Invalid GitHub URL. Please enter a valid repository link.")
 
