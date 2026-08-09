# AnalystGPT - AI-Powered Data Analysis Workbench

AnalystGPT is a premium, web-based AI-Powered Data Analysis Assistant built using Python Flask, Plotly.js, Tailwind CSS, Bootstrap 5, and the Groq Inference Engine. The application operates in a secure, responsive Dark Glassmorphism UI environment.

---

## Key Features

1. **Analytical Dashboard & Data Cleaning**: 
   - Drag-and-drop zone + file picker for uploading CSV datasets up to 50MB.
   - Comprehensive column data profiling (row counts, missing values, column listings, and datatypes).
   - Automated cleaning pipelines including duplicate removal, whitespace striping, casing correction, floating number standardizations, and custom null cell imputation options.
   
2. **AI Copilot (Groq Llama-3.3-70b-versatile)**:
   - Ask natural language questions about the CSV.
   - The AI writes and runs local Python functions (`analyze(df)`) inside a secure namespace sandbox to query variables and output answers and dynamic Plotly-ready datasets.
   
3. **Data Visualizations**:
   - Visualizes Bar, Line, Pie, and Scatter charts dynamically.
   - Users can manually override recommended chart configurations.
   
4. **PDF Reports Generation**:
   - Generates and downloads a custom ReportLab PDF document embedding user executive notes, dataset summaries, AI chat dialogues, and base64-decoded charts.
   
5. **Secure Authentication & OTP Routing**:
   - Login card supporting social provider OAuth pills.
   - Verification flow using secure 6-digit email OTPs.
   - Passwords hashing via `bcrypt`.

---

## Architectural Stack

- **Backend**: Python Flask (Application Factories & Blueprint Routing)
- **Frontend Styling**: Bootstrap 5 + Tailwind CSS (Curated Dark HSL Palette & blur-based Glassmorphism)
- **Visuals**: Plotly.js CDN
- **Database & Auth Integration**: Supabase (Client Wrapper) with automatic SQLite fallback (`data_analyst.db`)
- **AI Engine**: Groq API

---

## Setup & Running Instructions

### 1. Requirements & Virtual Environment
Ensure you have Python installed. The application is tested and optimized for modern environments.

```bash
# Navigate to the project directory
cd ai_data_analyst

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 2. Dependency Installation
Since Python 3.14+ lacks pre-compiled wheels for older library distributions, run:

```bash
pip install -r requirements.txt
```

*(This command uses flexible version controls to query the latest pre-compiled binaries).*

### 3. Environmental Configuration
Open `.env` and configure your API tokens:

- **`FLASK_SECRET_KEY`**: Security hash for session scopes.
- **`GROQ_API_KEY`**: Needed for the AI natural language engine. If omitted, the system defaults to a mock analysis engine for seamless testing.
- **`SUPABASE_URL` & `SUPABASE_KEY`**: If omitted, database queries fallback to local SQLite (`data_analyst.db`).
- **`SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD`**: If omitted, 6-digit OTP codes print to the terminal stdout and display in a local debug banner.

### 4. Running the Application

```bash
python app.py
```

The server launches at `http://localhost:5000`.

---

## Database Schemas (Supabase SQL Editor)
If you are linking your Supabase account, execute the following SQL script inside your Supabase project query console:

```sql
-- Create users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create OTPs table
CREATE TABLE otps (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    code TEXT NOT NULL,
    purpose TEXT NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
