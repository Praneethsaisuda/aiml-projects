import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
from PyPDF2 import PdfReader
import requests
import time
import json
import threading
import sqlite3
from tkinter import ttk
import csv
from difflib import SequenceMatcher

# Ollama Settings
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"

# Load job roles and descriptions from CSV
job_skills = {}
try:
    with open("job_description.csv", newline='', encoding="ISO-8859-1") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            title = row.get("Job Title", "").strip()
            description = row.get("Job Description", "").strip()
            if title and description:
                keywords = list(set(word.lower().strip(".,()") for word in description.split() if len(word) > 3))
                job_skills[title] = keywords[:20]
except Exception as e:
    print("Error loading job descriptions:", e)

# SQLite setup
conn = sqlite3.connect("resumes.db")
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS resumes (
    file TEXT PRIMARY KEY,
    role TEXT,
    skills TEXT,
    experience TEXT,
    education TEXT,
    certifications TEXT
)''')
conn.commit()

# Extract text from PDF
def extract_text_from_pdf(file_path):
    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() for page in reader.pages if page.extract_text())

# Analyze resume with Ollama
def analyze_resume_with_ollama(resume_text):
    prompt = f"""
You are a resume analyzer. Given the resume below, extract the most suitable job role, list the key technical skills, work experience (in brief), education (in brief), certifications if any, and notable projects.

Resume:
{resume_text[:800]}

Return your response in the following format:
Role: <Suggested Role>
Skills: <comma-separated skills>
Experience: <short description>
Education: <short description>
Certifications: <short list or 'None'>
Projects: <comma-separated project keywords>
    """
    try:
        print("Sending resume to Ollama model for analysis...")
        response = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        })
        data = response.json()
        print("Response received:", data.get("response", "No response field found"))
        return data.get("response", "⚠️ Unexpected response from Ollama")
    except Exception as e:
        print("Ollama error:", e)
        return f"❌ Ollama error: {e}"

# Match score calculation
def match_skills(resume_info, required_skills):
    content_parts = []
    content_parts.extend(resume_info.get("skills", []))
    content_parts.extend(resume_info.get("projects", []))

    education_text = resume_info.get("education", "").lower()
    experience_text = resume_info.get("experience", "").lower()
    certifications_text = resume_info.get("certifications", "").lower()

    if certifications_text:
        content_parts.extend(certifications_text.split())
    if education_text:
        content_parts.extend(education_text.split())
    if experience_text:
        content_parts.extend(experience_text.split())

    full_content = " ".join(content_parts).lower()
    matched = []

    for skill in required_skills:
        skill_lower = skill.lower()
        if skill_lower in full_content:
            matched.append(skill)
        else:
            for word in content_parts:
                if SequenceMatcher(None, skill_lower, word.lower()).ratio() > 0.8:
                    matched.append(skill)
                    break

    total_required = len(required_skills)
    skill_score = len(matched) / total_required if total_required else 0

    # Education score
    education_score = 0
    if "phd" in education_text or "doctorate" in education_text:
        education_score = 1.0
    elif "master" in education_text or "mba" in education_text:
        education_score = 0.75
    elif "bachelor" in education_text:
        education_score = 0.5

    # Certification score
    cert_score = 0
    if certifications_text and certifications_text != "none":
        keywords = ["aws", "azure", "google", "oracle", "pmp", "tensorflow", "ml", "data", "devops", "full stack"]
        cert_score = any(k in certifications_text for k in keywords) * 1.0

    # Experience score
    experience_score = 0
    if any(word in experience_text for word in ["engineer", "developer", "scientist", "analyst"]):
        experience_score = 1.0

    # Project score
    project_score = 1.0 if resume_info.get("projects") else 0

    # Weighted final score
    final_score = (
        skill_score * 0.50 +
        education_score * 0.20 +
        cert_score * 0.10 +
        experience_score * 0.15 +
        project_score * 0.05
    )

    match_percent = int(final_score * 100)
    return min(match_percent, 100), matched

# GUI Setup
ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")
app = ctk.CTk()
app.geometry("1024x768")
app.title("AI Resume Reviewer")

# Frames
main_frame = ctk.CTkFrame(app, fg_color="transparent")
main_frame.pack(padx=20, pady=20, fill="both", expand=True)

header = ctk.CTkLabel(main_frame, text="📄 AI Resume Reviewer", font=("Helvetica", 26, "bold"))
header.pack(pady=10)

status_label = ctk.CTkLabel(main_frame, text="Status: Waiting for input...", text_color="gray", font=("Helvetica", 14))
status_label.pack(pady=5)

role_label = ctk.CTkLabel(main_frame, text="Select Job Role:", font=("Helvetica", 16))
role_label.pack(pady=5)

job_role_var = ctk.StringVar()
job_role_menu = ctk.CTkOptionMenu(main_frame, variable=job_role_var, values=list(job_skills.keys()))
job_role_menu.pack(pady=5)

upload_button = ctk.CTkButton(main_frame, text="Upload Resume(s)", command=lambda: threading.Thread(target=process_resumes).start(), font=("Helvetica", 16), corner_radius=10, hover_color="#4da6ff")
upload_button.pack(pady=15)

result_frame = ctk.CTkScrollableFrame(main_frame, width=800, height=400, fg_color="#f2f2f2", border_width=1, border_color="#ccc")
result_frame.pack(pady=15, fill="both", expand=True)

# Animate status label
fade_step = 0
fade_direction = 1

def animate_status():
    global fade_step, fade_direction
    color = f"#{int(128 + fade_step):02x}{int(128 + fade_step):02x}{int(128 + fade_step):02x}"
    status_label.configure(text_color=color)
    fade_step += 5 * fade_direction
    if fade_step >= 100 or fade_step <= 0:
        fade_direction *= -1
    app.after(100, animate_status)

animate_status()

# Global Resume Data
resume_data = []

def process_resumes():
    result_frame._parent_canvas.yview_moveto(0)
    for widget in result_frame.winfo_children():
        widget.destroy()

    files = filedialog.askopenfilenames(filetypes=[("PDF Files", "*.pdf")])
    selected_role = job_role_var.get()
    if not selected_role or selected_role not in job_skills:
        messagebox.showwarning("Missing Role", "Please select a job role before uploading resumes.")
        return

    status_label.configure(text=f"⏳ Processing {len(files)} resume(s) for role: {selected_role}...")
    skills_required = job_skills[selected_role]

    for file_path in files:
        file_name = os.path.basename(file_path)
        resume_text = extract_text_from_pdf(file_path)
        ai_response = analyze_resume_with_ollama(resume_text)

        lines = ai_response.split("\n")
        info = {"skills": [], "projects": []}
        for line in lines:
            line = line.strip()
            if line.lower().startswith("role"):
                info["role"] = line.split(":", 1)[-1].strip()
            elif line.lower().startswith("skills"):
                info["skills"] = [s.strip().lower() for s in line.split(":", 1)[-1].split(",")]
            elif line.lower().startswith("experience"):
                info["experience"] = line.split(":", 1)[-1].strip()
            elif line.lower().startswith("education"):
                info["education"] = line.split(":", 1)[-1].strip()
            elif line.lower().startswith("certifications"):
                info["certifications"] = line.split(":", 1)[-1].strip()
            elif line.lower().startswith("projects"):
                info["projects"] = [p.strip().lower() for p in line.split(":", 1)[-1].split(",")]

        score, matched = match_skills(info, skills_required)
        resume_data.append({"name": file_name, "score": score, "details": info, "matched": matched})

    resume_data.sort(key=lambda x: x["score"], reverse=True)
    status_label.configure(text=f"✅ Processed {len(resume_data)} resume(s) for '{selected_role}' role")

    for resume in resume_data:
        label = ctk.CTkLabel(result_frame, text=f"{resume['name']} - Match Score: {resume['score']}%\nRole: {resume['details'].get('role')}\nSkills: {', '.join(resume['details'].get('skills', []))}", anchor="w", justify="left", font=("Helvetica", 14))
        label.pack(anchor="w", padx=10, pady=8)

app.mainloop()
