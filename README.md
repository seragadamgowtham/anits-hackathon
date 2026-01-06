🎓 GATE Master - AI-Powered Learning Management System
GATE Master is a Flask-based web application designed to automate the creation of study materials and assessments for the Graduate Aptitude Test in Engineering (GATE).

It uses Local AI (Ollama) to read uploaded documents (PDFs, DOCX, Images), automatically generate study notes, create quizzes, and act as a conversational tutor for students.

✨ Key Features
👨‍🏫 For Teachers
Content Upload: Support for PDF, DOCX, TXT, and Image files.

AI Automation: Automatically generates Study Notes (HTML formatted) and MCQ Quizzes (JSON) from uploaded files.

Dual Set Generation: Creates two variation sets per topic:

Set A: Conceptual & Theory.

Set B: Applied & Numerical.

Analytics: View detailed student results and leaderboards.

👨‍🎓 For Students
Dashboard: Track CGPA and pending assignments.

Exam Arena: Take timed quizzes with Anti-Cheat monitoring (tracks tab switching/malpractice).

AI Tutor: Chat with an AI that has context of the specific files uploaded by the teacher to clear doubts.

Instant Results: Get immediate scoring and performance feedback.

🛠️ Tech Stack
Backend: Python (Flask)

Database: SQLite (gate_v3.sqlite)

AI Engine: Ollama (running locally)

AI Model: Google Gemma 3 (gemma3)

Document Processing: pypdf, python-docx, Pillow (Images), pytesseract (OCR).

⚙️ Prerequisites
Python 3.8+ installed.

Ollama installed and running on your machine.
