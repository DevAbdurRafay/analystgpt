<h1 align="center">AnalystGPT — AI-Powered Data Analysis Workbench</h1>
<p align="center"><strong>AnalystGPT</strong> is a premium, web-based <strong>AI-Powered Data Analysis Assistant</strong> built using <strong>Python Flask</strong>, <strong>Plotly.js</strong>, <strong>Tailwind CSS</strong>, <strong>Bootstrap 5</strong>, and the <strong>Groq Inference Engine</strong>. The application operates in a secure, responsive <strong>Dark Glassmorphism UI</strong> environment, letting users upload a dataset and chat with an AI copilot to instantly generate insights, charts, and reports.</p>

<h2>🚀 Key Features</h2>

<h3>📊 Analytical Dashboard & Data Cleaning</h3>
<ul>
  <li>Drag-and-drop zone + file picker for uploading CSV/Excel datasets up to 50MB.</li>
  <li>Comprehensive column data profiling — row counts, missing value counts & percentages, unique value counts, and column datatypes.</li>
  <li>Automated cleaning pipeline: header normalization, whitespace/casing correction (with acronym preservation), duplicate removal, data type correction, and automatic date parsing.</li>
</ul>

<h3>🤖 AI Copilot (Groq Llama-3.3-70b-versatile + Gemini Fallback)</h3>
<ul>
  <li>Ask natural language questions about your dataset — including on-the-fly calculations (averages, totals, groupby aggregations) that aren't even direct columns.</li>
  <li>The AI writes and runs local Python functions (<code>analyze(df)</code>) inside a secure namespace sandbox to query variables and output answers with dynamic Plotly/Matplotlib-ready datasets.</li>
  <li>Automatic failover to Google Gemini if the Groq API hits a rate limit, with zero visible interruption to the user.</li>
</ul>

<h3>📈 Data Visualizations</h3>
<ul>
  <li>Generates Bar, Line, Pie, Donut, Scatter, Histogram, Area, and Correlation Heatmap charts dynamically based on your prompt.</li>
  <li>Every chart includes clearly labeled axes, titles, and multi-color palettes readable against the dark theme.</li>
  <li>Users can manually override recommended chart types via a custom-styled dropdown selector.</li>
</ul>

<h3>📄 PDF Reports Generation</h3>
<ul>
  <li>Generates and downloads a custom ReportLab PDF document embedding user executive notes, dataset summaries, AI chat dialogues, and embedded charts.</li>
</ul>

<h3>🔐 Secure Authentication & OTP Routing</h3>
<ul>
  <li>Login card supporting Google and GitHub OAuth via Flask-Dance, alongside standard email/password sign-up.</li>
  <li>Verification flow using secure 4-digit email OTPs.</li>
  <li>Passwords hashed via <code>bcrypt</code>; sessions secured with a fixed <code>FLASK_SECRET_KEY</code>.</li>
</ul>

<h2>🛠️ Tech Stack</h2>
<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white" alt="Supabase" />
  <img src="https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logo=groq&logoColor=white" alt="Groq" />
  <img src="https://img.shields.io/badge/Google_Gemini-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white" alt="Gemini" />
  <img src="https://img.shields.io/badge/Plotly-3F4F75?style=for-the-badge&logo=plotly&logoColor=white" alt="Plotly" />
  <img src="https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/Bootstrap-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white" alt="Bootstrap" />
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white" alt="HTML5" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript" />
</p>

<h2>🏗️ Architectural Stack</h2>
<ul>
  <li><strong>Backend:</strong> Python Flask (Application Factories & Blueprint Routing)</li>
  <li><strong>Frontend Styling:</strong> Bootstrap 5 + Tailwind CSS (Curated Dark HSL Palette & blur-based Glassmorphism)</li>
  <li><strong>Visuals:</strong> Plotly.js CDN + Matplotlib/Seaborn (server-rendered charts)</li>
  <li><strong>Database & Auth Integration:</strong> Supabase (PostgreSQL via Client Wrapper + Session Pooler)</li>
  <li><strong>AI Engine:</strong> Groq API (primary) with Google Gemini API (automatic fallback)</li>
</ul>

<h2>🛣️ Routes & Database Architecture</h2>
<ul>
  <li><strong>Authenticated Route Guarding:</strong> Every dashboard, analytics, and chat route checks for an active Flask session and redirects unauthenticated users back to the login page.</li>
  <li><strong>OAuth Callback Routes:</strong> Dedicated Google (<code>/login/google/authorized</code>) and GitHub (<code>/login/github/authorized</code>) callback endpoints handled via Flask-Dance blueprints.</li>
  <li><strong>Database & Pooling Connection:</strong> Connects to Supabase via a secure connection string, optimized with a <strong>Session Pooler</strong> to manage concurrent database sessions efficiently.</li>
</ul>

<h2>⚙️ Setup & Installation</h2>

<h3>1. Requirements & Virtual Environment</h3>
<p>Ensure you have Python installed, then set up your virtual environment:</p>
<pre><code># Navigate to the project directory
cd ai_data_analyst

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate</code></pre>

<h3>2. Dependency Installation</h3>
<pre><code>pip install -r requirements.txt</code></pre>

<h3>3. Configure Environment Variables</h3>
<p>Create a <code>.env</code> file in the root directory (see <code>.env.example</code>) and add your credentials:</p>
<pre><code># Supabase (database only — NOT used for authentication)
SUPABASE_URL=your-supabase-project-url
SUPABASE_ANON_KEY=your-supabase-anon-key
DATABASE_URL=your-supabase-session-pooler-connection-string

# AI Engine
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.3-70b-versatile
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash

# Flask
FLASK_SECRET_KEY=your-flask-secret-key
FLASK_ENV=development
APP_BASE_URL=http://localhost:5000

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

# GitHub OAuth
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret</code></pre>

<h3>4. Run the Application</h3>
<pre><code>python app.py</code></pre>
<p>The server launches at <code>http://localhost:5000</code>.</p>

<h2>📂 Project Structure</h2>
<ul>
  <li><code>app.py</code> - Application factory, environment validation, and route registration.</li>
  <li><code>api/</code> - Serverless entry point used for deployment.</li>
  <li><code>routes/</code> - Flask blueprints for authentication, data handling, and AI chat.</li>
  <li><code>services/</code> - Supabase client, Groq/Gemini AI service, email service.</li>
  <li><code>templates/</code> - Jinja2 HTML templates for the dashboard, login, and chat UI.</li>
  <li><code>static/</code> - CSS styles and frontend assets.</li>
  <li><code>tests/</code> - Test suite for the application.</li>
  <li><code>.env.example</code> - Template listing required environment variables.</li>
  <li><code>.python-version</code> - Pinned Python version for consistent environments.</li>
  <li><code>pyproject.toml</code> - Python project/build configuration.</li>
  <li><code>requirements.txt</code> - Python dependencies.</li>
  <li><code>tailwind.config.js</code> - Tailwind CSS configuration.</li>
</ul>

<hr />
<p align="center"><em>Built as an AI-powered data analysis platform for the Hackathon 2026 project.</em></p>
