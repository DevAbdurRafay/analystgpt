import os
import re
import io
import json
import base64
import logging
import time
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_FALLBACK_MODELS = [
    m for m in [
        GEMINI_MODEL,
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ] if m
]

GROQ_FALLBACK_MODELS = [
    m for m in [
        GROQ_MODEL,
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama-3.1-70b-versatile",
    ] if m
]

MAX_API_RETRIES = 3
RETRY_BASE_DELAY_SEC = 0.75

EMPTY_CHART_RESULT = {
    "chart_type": None,
    "chart_title": None,
    "chart_data": None,
    "chart_image_base64": None,
    "charts": [],
}


def _save_plot_to_base64():
    """Utility injected into sandbox: saves the current matplotlib figure to a base64 PNG string."""
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor='#0d1117', edgecolor='none')
    plt.close('all')
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode('utf-8')
    return f"data:image/png;base64,{b64}"


class GroqService:
    def __init__(self):
        self.api_key = GROQ_API_KEY
        self.model = GROQ_MODEL
        self.gemini_api_key = GEMINI_API_KEY
        self.gemini_model = GEMINI_MODEL
        if self.api_key:
            self.client = Groq(api_key=self.api_key)
        else:
            self.client = None

    def _ensure_groq_client(self) -> bool:
        """Lazy-init Groq client if an API key becomes available."""
        if self.client:
            return True
        load_dotenv(override=True)
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", self.model)
        if self.api_key:
            try:
                self.client = Groq(api_key=self.api_key)
                return True
            except Exception as exc:
                logger.warning("Failed to initialize Groq client: %s", exc)
        return False

    def _groq_failure_reason(self, exc: Exception) -> str:
        """Describe why a Groq call failed (for server-side fallback logging)."""
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if status is None and response is not None:
            status = getattr(response, "status_code", None)

        if status == 429:
            return "Groq rate limit hit (HTTP 429)"

        message = str(exc).lower()
        if any(token in message for token in ("rate_limit", "rate limit", "rate_limit_exceeded", "too many requests")):
            return "Groq rate limit exceeded"

        if status is not None and 500 <= int(status) < 600:
            return f"Groq server error (HTTP {status})"

        exc_name = type(exc).__name__.lower()
        if any(token in exc_name for token in ("ratelimit", "timeout", "connection", "apierror", "internalserver")):
            return f"Groq API error ({type(exc).__name__})"

        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return "Groq connection/timeout error"

        return f"Groq API failure ({type(exc).__name__}: {exc})"

    def _is_rate_limit(self, exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status == 429:
            return True
        message = str(exc).lower()
        return any(token in message for token in ("rate_limit", "rate limit", "too many requests", "429"))

    def _call_groq(self, system_prompt: str, user_query: str, model: str | None = None) -> str:
        """Call Groq chat completions and return raw model text."""
        chat_completion = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
            model=model or self.model,
            temperature=0.05,
            max_tokens=4000,
        )
        return chat_completion.choices[0].message.content or ""

    def _call_groq_with_retries(self, system_prompt: str, user_query: str) -> str:
        """Try multiple Groq models with short retries on rate limits."""
        seen = set()
        models = []
        for name in GROQ_FALLBACK_MODELS:
            if name not in seen:
                seen.add(name)
                models.append(name)

        last_error = None
        for model_name in models:
            for attempt in range(MAX_API_RETRIES):
                try:
                    text = self._call_groq(system_prompt, user_query, model=model_name)
                    if text.strip():
                        if model_name != self.model:
                            logger.info("Groq succeeded using fallback model %s", model_name)
                        return text
                    raise RuntimeError("Groq returned an empty response")
                except Exception as exc:
                    last_error = exc
                    if self._is_rate_limit(exc) and attempt < MAX_API_RETRIES - 1:
                        delay = RETRY_BASE_DELAY_SEC * (attempt + 1)
                        logger.warning("Groq rate limit on %s, retrying in %.1fs", model_name, delay)
                        time.sleep(delay)
                        continue
                    logger.warning("Groq model %s failed: %s", model_name, exc)
                    break

        raise RuntimeError(f"All Groq models failed: {last_error}")

    def _call_gemini(self, system_prompt: str, user_query: str) -> str:
        """Call Gemini with the same instructions as Groq."""
        api_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        seen = set()
        models_to_try = []
        for name in GEMINI_FALLBACK_MODELS:
            if name not in seen:
                seen.add(name)
                models_to_try.append(name)

        last_error = None
        for model_name in models_to_try:
            for attempt in range(MAX_API_RETRIES):
                try:
                    try:
                        model = genai.GenerativeModel(model_name, system_instruction=system_prompt)
                        prompt = user_query
                    except Exception:
                        model = genai.GenerativeModel(model_name)
                        prompt = f"{system_prompt}\n\nUser question:\n{user_query}"

                    response = model.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0.05,
                            "max_output_tokens": 4000,
                        },
                    )

                    text = getattr(response, "text", None)
                    if text:
                        logger.info("Gemini response succeeded using model %s", model_name)
                        return text

                    candidates = getattr(response, "candidates", None) or []
                    for candidate in candidates:
                        content = getattr(candidate, "content", None)
                        parts = getattr(content, "parts", None) if content else None
                        if parts:
                            joined = "".join(getattr(part, "text", "") or "" for part in parts)
                            if joined.strip():
                                logger.info("Gemini response succeeded using model %s", model_name)
                                return joined

                    raise RuntimeError("Gemini returned an empty response")
                except Exception as exc:
                    last_error = exc
                    if self._is_rate_limit(exc) and attempt < MAX_API_RETRIES - 1:
                        delay = RETRY_BASE_DELAY_SEC * (attempt + 1)
                        logger.warning("Gemini rate limit on %s, retrying in %.1fs", model_name, delay)
                        time.sleep(delay)
                        continue
                    logger.warning("Gemini model %s failed: %s", model_name, exc)
                    break

        raise RuntimeError(f"All Gemini models failed: {last_error}")

    def _generate_llm_response(self, system_prompt: str, user_query: str) -> str:
        """
        Try Groq first; on any Groq API failure, silently retry with Gemini.
        Raises if both providers fail.
        """
        groq_error = None

        if self._ensure_groq_client():
            try:
                return self._call_groq_with_retries(system_prompt, user_query)
            except Exception as exc:
                groq_error = exc
                reason = self._groq_failure_reason(exc)
                logger.warning("%s, falling back to Gemini", reason)

        try:
            response_text = self._call_gemini(system_prompt, user_query)
            if groq_error is not None:
                logger.info("Gemini fallback succeeded after Groq failure")
            return response_text
        except Exception as gemini_exc:
            if groq_error is not None:
                logger.error(
                    "Gemini fallback also failed after Groq error: %s",
                    gemini_exc,
                )
            else:
                logger.error("Gemini request failed (Groq unavailable): %s", gemini_exc)
            raise RuntimeError("All AI providers failed") from gemini_exc

    def query_data(self, df: pd.DataFrame, user_query: str) -> dict:
        """Analyzes a dataframe based on ANY user query."""
        prompt = (user_query or "").strip()

        if not self._ensure_groq_client() and not (self.gemini_api_key or os.getenv("GEMINI_API_KEY")):
            return self._normalize_result(self._resolve_offline(df, prompt))

        schema_summary = self._generate_schema_summary(df)

        system_prompt = f"""You are AnalystGPT — the world's most advanced data analyst AI assistant. You have expertise in:
- Pandas, NumPy, statistics, and data storytelling
- Scikit-learn (sklearn): regression, classification, clustering, PCA, preprocessing, train/test split, metrics
- SciPy & statsmodels: hypothesis tests, distributions, OLS/regression, time-series basics
- Time intelligence (Previous Month, Previous Quarter, Previous Year, YoY growth, MoM change, Rolling averages)
- DAX-equivalent calculations implemented in Python/Pandas
- Advanced visualizations using Matplotlib, Seaborn, AND Plotly-compatible data
- Correlation analysis, distribution analysis, outlier detection, regression analysis
- Creating ANY type of chart the user asks for

AVAILABLE LIBRARIES (already installed — import freely inside analyze()):
- pandas as pd, numpy as np
- matplotlib.pyplot as plt, seaborn as sns
- sklearn (preprocessing, cluster, decomposition, linear_model, metrics, model_selection, ensemble)
- scipy, scipy.stats
- statsmodels.api as sm
- json, re, io, math, datetime

The dataset is a pandas DataFrame named `df`. Schema and stats:
{schema_summary}

INSTRUCTIONS:
Write a Python function with the EXACT signature `def analyze(df):` that answers the user's question.

The function MUST return a Python dict with these keys:
- "answer" (str, REQUIRED): A detailed, human-readable Markdown response. Use **bold**, bullet points, tables (as markdown), code snippets. Always give specific numbers. For DAX formulas, include the equivalent Python/Pandas code AND the DAX formula.
- "chart_type" (str or None): For Plotly charts: one of "bar", "line", "pie", "scatter", "histogram", "heatmap_plotly". Set to None if using matplotlib/seaborn instead.
- "chart_title" (str or None): Chart title.
- "chart_data" (dict or None): For Plotly charts:
  - bar/line/pie: {{"labels": [...], "values": [...], "orientation": "h" or "v", "colors": [list of hex color strings or None]}}
  - scatter: {{"x": [...], "y": [...], "x_label": "...", "y_label": "...", "colors": [...]}}
  - heatmap_plotly: {{"z": [[...]], "x": [...], "y": [...], "colorscale": "RdYlGn"}}
  - Set to None if using matplotlib/seaborn.
- "chart_image_base64" (str or None): If using matplotlib/seaborn, call `save_plot_to_base64()` AFTER creating your figure and set this to its return value. Otherwise None.
- "charts" (list, optional): For MULTIPLE visualizations (e.g. top 5 + bottom 5 tables, side-by-side comparisons), return a list of chart objects:
  [{{"title": "Chart 1 title", "chart_type": "bar"|None, "chart_data": {{...}}|None, "chart_image_base64": "..."|None}}, ...]
  Use matplotlib/seaborn with subplots OR call save_plot_to_base64() separately for each figure (always plt.close() between figures).
  When "charts" is used, ALSO mirror the FIRST chart into chart_type/chart_title/chart_data/chart_image_base64 for compatibility.

VISUALIZATION RULES (IMPORTANT):
- ALWAYS provide a complete numeric answer in "answer" with exact counts/values from the data.
- Include a visualization whenever it helps: counts, comparisons, trends, top/bottom lists, duplicates, distributions.
- For duplicate-row questions, compute df.duplicated().sum() and show a chart comparing duplicate vs unique rows.
- For multiple requested views (e.g. best AND worst, top AND bottom), use the "charts" list with one entry per visualization.

MATPLOTLIB/SEABORN CHART GUIDE (use for: heatmaps, pairplots, horizontal bars, violin plots, box plots, custom correlation matrices, multi-series with custom colors):
```python
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

# Always use dark theme:
plt.style.use('dark_background')
plt.rcParams['figure.facecolor'] = '#0d1117'
plt.rcParams['axes.facecolor'] = '#161b22'
plt.rcParams['text.color'] = '#e2e8f0'
plt.rcParams['axes.labelcolor'] = '#e2e8f0'
plt.rcParams['xtick.color'] = '#cbd5e1'
plt.rcParams['ytick.color'] = '#cbd5e1'
plt.rcParams['grid.color'] = '#30363d'

# Custom color palette example:
COLORS = ['#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#F97316', '#14B8A6']
sns.set_palette(COLORS)

# After plotting, call:
chart_image_base64 = save_plot_to_base64()
```

TIME INTELLIGENCE GUIDE (VERY IMPORTANT):
If user asks about previous month, quarter, year — detect date columns and use this pattern:
```python
# Try to convert date columns
for col in df.columns:
    if df[col].dtype == 'object':
        try:
            df[col] = pd.to_datetime(df[col], infer_datetime_format=True, errors='coerce')
        except: pass

# Find date column (first datetime column)
date_col = next((c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])), None)

if date_col:
    df['_year'] = df[date_col].dt.year
    df['_month'] = df[date_col].dt.month
    df['_quarter'] = df[date_col].dt.quarter
    
    # Get current (latest) period
    max_date = df[date_col].max()
    cur_month, cur_year = max_date.month, max_date.year
    
    # Previous month logic
    prev_month = 12 if cur_month == 1 else cur_month - 1
    prev_month_year = cur_year - 1 if cur_month == 1 else cur_year
    
    # Previous quarter
    cur_quarter = (cur_month - 1) // 3 + 1
    prev_quarter = 4 if cur_quarter == 1 else cur_quarter - 1
    prev_quarter_year = cur_year - 1 if cur_quarter == 1 else cur_year
    
    # Previous year
    prev_year = cur_year - 1
```

DAX EQUIVALENT GUIDE:
When asked for DAX formulas, provide BOTH the DAX measure AND the Pandas equivalent:
- CALCULATE() → df.loc[mask, col].sum()
- PREVIOUSMONTH() → filter by (month == prev_month AND year == prev_month_year)
- SAMEPERIODLASTYEAR() → filter by (year == cur_year - 1 AND same month range)
- DATESBETWEEN() → df[(df[date_col] >= start) & (df[date_col] <= end)]
- TOTALYTD() → df[df[date_col].dt.year == cur_year][value_col].sum()

RULES (STRICTLY FOLLOW):
1. Output ONLY executable Python code. NO text outside the function.
2. ALWAYS use try/except inside the function.
3. ALL values in returned dict must be JSON-serializable. Convert numpy types with int()/float(), replace NaN/Inf with None or 0.
4. Do NOT read any file — df is already in memory.
5. For chart colors, use varied vivid colors like: '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'
6. For horizontal bar charts, set orientation='h' in chart_data.
7. For correlation heatmaps or complex charts, use seaborn (chart_image_base64).
8. For simple bar/line/pie/scatter, use Plotly-compatible chart_data format.

CORRELATION & COLUMN RELATIONSHIP GUIDE (CRITICAL):
When the user asks how columns relate, correlate, or depend on each other (e.g. "relationship between columns", "correlation heatmap", "which columns are related"):
1. Select all numeric columns: `numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()`
2. Compute Pearson correlation: `corr = df[numeric_cols].corr(numeric_only=True)`
3. ALWAYS return an interactive Plotly heatmap:
   - chart_type: "heatmap_plotly"
   - chart_data: {{"z": corr.round(3).fillna(0).values.tolist(), "x": corr.columns.tolist(), "y": corr.columns.tolist(), "colorscale": "RdYlGn"}}
4. In "answer", list the top 3–5 strongest pairs with correlation values and strength labels (|r| > 0.7 strong, 0.4–0.7 moderate, < 0.4 weak).
5. Only use scatter when the user names TWO specific columns with "vs" (e.g. "sales vs profit scatter").

9. Always compute REAL answers from the data — never guess or hallucinate values.
10. Column names may have spaces or mixed case — use EXACT names from the schema above.

EXAMPLE (time intelligence with chart):
```python
def analyze(df):
    import pandas as pd
    import numpy as np
    try:
        # detect date col
        date_col = None
        for col in df.columns:
            if df[col].dtype == 'object':
                try:
                    test = pd.to_datetime(df[col], errors='coerce')
                    if test.notna().sum() > len(df) * 0.5:
                        df[col] = test
                except: pass
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                date_col = col
                break
        
        sales_col = 'total_price'  # Use actual column from schema
        
        if date_col is None:
            return {{"answer": "No date column detected.", "chart_type": None, "chart_title": None, "chart_data": None, "chart_image_base64": None}}
        
        df['_ym'] = df[date_col].dt.to_period('M')
        monthly = df.groupby('_ym')[sales_col].sum()
        
        answer = "**Monthly Sales:**\\n"
        for period, val in monthly.tail(6).items():
            answer += f"- {{period}}: **{{val:,.2f}}**\\n"
        
        labels = [str(p) for p in monthly.index.tolist()]
        values = [float(v) if not np.isnan(v) else 0 for v in monthly.values.tolist()]
        
        return {{
            "answer": answer,
            "chart_type": "line",
            "chart_title": "Monthly Sales Trend",
            "chart_data": {{"labels": labels, "values": values}},
            "chart_image_base64": None
        }}
    except Exception as e:
        return {{"answer": f"Error: {{str(e)}}", "chart_type": None, "chart_title": None, "chart_data": None, "chart_image_base64": None}}
```
"""

        try:
            response_text = self._generate_llm_response(system_prompt, user_query)
            cleaned_code = self._extract_python_code(response_text)
            result = self._normalize_result(self._execute_code(cleaned_code, df))
            result = self._augment_correlation_chart(result, df, user_query)
            answer = (result.get("answer") or "").strip()
            if answer and not answer.lower().startswith("error:"):
                return result
            logger.warning("Generated analysis returned an error answer, using fallback chain")
        except RuntimeError:
            logger.warning("All AI providers failed for code generation, using fallback chain")
        except Exception as e:
            logger.exception("Failed to execute generated analysis code: %s", e)

        return self._normalize_result(self._resolve_offline(df, prompt))

    def _resolve_offline(self, df: pd.DataFrame, user_query: str) -> dict:
        """Answer from local analysis, direct LLM, or smart pandas fallback — never empty."""
        direct = self._try_direct_llm_answer(df, user_query)
        if direct:
            logger.info("Serving direct LLM answer fallback")
            return direct

        local = self._try_local_analysis(df, user_query)
        if local:
            logger.info("Serving local heuristic analysis")
            return local

        return self._build_smart_fallback_answer(df, user_query)

    def _try_direct_llm_answer(self, df: pd.DataFrame, user_query: str) -> dict | None:
        """Simpler LLM call: answer in Markdown from schema + sample rows (no code execution)."""
        if not self._ensure_groq_client() and not (self.gemini_api_key or os.getenv("GEMINI_API_KEY")):
            return None

        schema = self._generate_schema_summary(df)
        sample_rows = df.head(20).to_csv(index=False)
        system_prompt = (
            "You are AnalystGPT, an expert data analyst. Answer the user's question using ONLY "
            "the dataset schema and sample rows provided.\n"
            "Rules:\n"
            "- Return a clean Markdown answer with **bold** key values.\n"
            "- Use exact column names and real values from the sample when possible.\n"
            "- For lookups (e.g. roll number of a person), search sample rows and state the value clearly.\n"
            "- If the exact value is not in the sample, say which column would contain it and how to find it.\n"
            "- Do NOT output Python code or code blocks.\n"
            "- Keep the answer concise and user-friendly.\n\n"
            f"Dataset schema:\n{schema}\n\nSample rows (CSV):\n{sample_rows}"
        )

        try:
            text = self._generate_llm_response(system_prompt, user_query).strip()
            if not text or "```" in text:
                return None
            return {"answer": text, **EMPTY_CHART_RESULT}
        except RuntimeError:
            return None

    def _find_columns_by_keywords(self, columns, keywords: list[str]) -> list:
        matches = []
        for col in columns:
            normalized = re.sub(r"[_\-]+", " ", str(col).lower())
            if any(kw in normalized for kw in keywords):
                matches.append(col)
        return matches

    def _extract_lookup_subject(self, user_query: str) -> str | None:
        query = (user_query or "").strip()
        patterns = [
            r"(?:roll\s*no\.?|roll\s*number|registration\s*no\.?|id|email|phone|grade|marks?|score|salary|age|gpa)\s*(?:of|for|or)\s+(.+?)(?:\?|$)",
            r"what\s+(?:is|are)\s+(?:the\s+)?(?:.+?\s+)?(?:of|for)\s+(.+?)(?:\?|$)",
            r"find\s+(?:the\s+)?(?:roll\s*no\.?|roll\s*number|.+?)\s+(?:of|for)\s+(.+?)(?:\?|$)",
            r"(.+?)'s\s+(?:roll\s*no\.?|roll\s*number|id|email|grade|marks?|score|salary|age)",
        ]
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                subject = match.group(1).strip().strip('?"\' ')
                if subject and len(subject) >= 2:
                    return subject
        return None

    def _target_columns_from_query(self, df: pd.DataFrame, user_query: str) -> list:
        q = (user_query or "").lower()
        keyword_map = {
            "roll": ["roll", "rollno", "roll no", "roll number", "registration"],
            "id": ["id", "student id", "employee id", "user id"],
            "email": ["email", "e-mail", "mail"],
            "phone": ["phone", "mobile", "contact", "cell"],
            "grade": ["grade", "class", "section"],
            "marks": ["marks", "mark", "score", "result", "gpa", "cgpa"],
            "salary": ["salary", "pay", "wage", "compensation"],
            "age": ["age"],
            "city": ["city", "location", "address"],
            "department": ["department", "dept", "division"],
        }
        for _, keywords in keyword_map.items():
            if any(kw in q for kw in keywords):
                cols = self._find_columns_by_keywords(df.columns, keywords)
                if cols:
                    return cols

        mentioned = self._extract_column_names(user_query, df.columns)
        return mentioned or []

    def _search_columns_from_query(self, df: pd.DataFrame) -> list:
        name_cols = self._find_columns_by_keywords(
            df.columns,
            ["name", "student", "employee", "person", "full name", "candidate", "user"],
        )
        if name_cols:
            return name_cols

        text_cols = df.select_dtypes(include=["object"]).columns.tolist()
        return text_cols[:3]

    def _match_rows_by_subject(self, df: pd.DataFrame, search_cols: list, subject: str) -> pd.DataFrame:
        subject_lower = subject.lower().strip()
        if not subject_lower:
            return pd.DataFrame()

        for col in search_cols:
            series = df[col].astype(str).str.lower()
            exact = df[series == subject_lower]
            if not exact.empty:
                return exact

            contains = df[series.str.contains(re.escape(subject_lower), na=False, regex=True)]
            if not contains.empty:
                return contains

            words = [w for w in re.split(r"\s+", subject_lower) if len(w) >= 3]
            if len(words) >= 2:
                mask = pd.Series(True, index=df.index)
                for word in words:
                    mask &= series.str.contains(re.escape(word), na=False, regex=True)
                partial = df[mask]
                if not partial.empty:
                    return partial

        return pd.DataFrame()

    def _format_row_answer(
        self,
        df: pd.DataFrame,
        matches: pd.DataFrame,
        subject: str,
        target_cols: list,
        search_col,
    ) -> str:
        if len(matches) == 1:
            row = matches.iloc[0]
            if target_cols:
                target_col = target_cols[0]
                value = row[target_col]
                label = row[search_col] if search_col is not None else subject
                return f"**{target_col}** for **{label}**: **`{value}`**"

            lines = [f"**Record found for {subject}:**"]
            for col in df.columns[:12]:
                lines.append(f"- **{col}**: `{row[col]}`")
            return "\n".join(lines)

        lines = [f"Found **{len(matches)}** matching records for **{subject}**:\n"]
        for _, row in matches.head(8).iterrows():
            label = row[search_col] if search_col is not None else subject
            if target_cols:
                details = ", ".join(f"**{col}** = `{row[col]}`" for col in target_cols[:3])
                lines.append(f"- **{label}**: {details}")
            else:
                preview = ", ".join(f"**{col}**=`{row[col]}`" for col in df.columns[:4])
                lines.append(f"- {preview}")
        if len(matches) > 8:
            lines.append(f"\n*Showing 8 of {len(matches)} matches.*")
        return "\n".join(lines)

    def _try_value_lookup(self, df: pd.DataFrame, user_query: str) -> dict | None:
        subject = self._extract_lookup_subject(user_query)
        if not subject:
            return None

        target_cols = self._target_columns_from_query(df, user_query)
        search_cols = self._search_columns_from_query(df)
        if not search_cols:
            return None

        for search_col in search_cols:
            matches = self._match_rows_by_subject(df, [search_col], subject)
            if matches.empty:
                continue
            answer = self._format_row_answer(df, matches, subject, target_cols, search_col)
            return {"answer": answer, **EMPTY_CHART_RESULT}

        return None

    def _try_column_stat(self, df: pd.DataFrame, user_query: str) -> dict | None:
        q = (user_query or "").lower()
        stat_map = {
            "average": "mean",
            "avg": "mean",
            "mean": "mean",
            "sum": "sum",
            "total": "sum",
            "maximum": "max",
            "max": "max",
            "minimum": "min",
            "min": "min",
            "median": "median",
            "count": "count",
        }
        stat_key = next((key for key in stat_map if re.search(rf"\b{re.escape(key)}\b", q)), None)
        if not stat_key:
            return None

        mentioned = self._extract_column_names(user_query, df.columns)
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        col = mentioned[0] if mentioned else (numeric_cols[0] if len(numeric_cols) == 1 else None)
        if col is None or col not in df.columns:
            return None

        series = df[col].dropna()
        if series.empty:
            return {"answer": f"**{col}** has no valid values to analyze.", **EMPTY_CHART_RESULT}

        op = stat_map[stat_key]
        if op == "count":
            value = int(series.count())
        elif op == "mean":
            value = round(float(series.mean()), 4)
        elif op == "median":
            value = round(float(series.median()), 4)
        else:
            value = round(float(getattr(series, op)()), 4)

        return {
            "answer": f"**{stat_key.title()} of {col}:** **{value}**",
            **EMPTY_CHART_RESULT,
        }

    def _try_filter_count(self, df: pd.DataFrame, user_query: str) -> dict | None:
        q = (user_query or "").lower()
        if not any(token in q for token in ("how many", "count", "number of")):
            return None

        match = re.search(r"(?:how many|count|number of)\s+(.+?)(?:\?|$)", q, re.IGNORECASE)
        if not match:
            return None

        phrase = match.group(1).strip()
        for col in df.columns:
            col_lower = str(col).lower()
            if col_lower not in phrase and col_lower.replace("_", " ") not in phrase:
                continue

            value_part = phrase.replace(col_lower, "").replace(col_lower.replace("_", " "), "").strip()
            value_part = re.sub(r"\b(in|with|where|having|are|is|the|records|rows)\b", " ", value_part).strip()
            if not value_part:
                counts = df[col].value_counts().head(10)
                lines = [f"**Value counts for {col}:**"]
                for idx, cnt in counts.items():
                    lines.append(f"- **{idx}**: {int(cnt)}")
                return {"answer": "\n".join(lines), **EMPTY_CHART_RESULT}

            series = df[col].astype(str).str.lower()
            filtered = df[series.str.contains(re.escape(value_part.lower()), na=False)]
            return {
                "answer": f"**Matching rows where {col} contains '{value_part}':** **{len(filtered)}**",
                **EMPTY_CHART_RESULT,
            }

        return None

    def _try_unique_values(self, df: pd.DataFrame, user_query: str) -> dict | None:
        q = (user_query or "").lower()
        if not any(token in q for token in ("unique", "distinct", "different values", "list values")):
            return None

        mentioned = self._extract_column_names(user_query, df.columns)
        if not mentioned:
            return None

        col = mentioned[0]
        values = df[col].dropna().astype(str).unique().tolist()[:20]
        answer = f"**Unique values in {col}** ({len(values)} shown):\n"
        answer += ", ".join(f"`{v}`" for v in values)
        if df[col].nunique() > len(values):
            answer += f"\n\n*Total unique values: {df[col].nunique()}*"
        return {"answer": answer, **EMPTY_CHART_RESULT}

    def _build_smart_fallback_answer(self, df: pd.DataFrame, user_query: str) -> dict:
        """Always return a useful cleaned answer when AI and heuristics miss."""
        overview = self._build_dataset_overview(df, user_query)
        columns_preview = ", ".join(f"`{c}`" for c in df.columns[:10])
        answer = (
            f"{overview['answer']}\n\n"
            f"**Your question:** *{user_query}*\n\n"
            f"I analyzed the dataset locally using available columns: {columns_preview}.\n"
            f"Try asking with an exact column name, e.g. "
            f"*\"Roll No of [name]\"* or *\"average [column]\"*."
        )
        return {"answer": answer, **EMPTY_CHART_RESULT}

    def _try_local_analysis(self, df: pd.DataFrame, user_query: str) -> dict | None:
        """Offline fallback for common dataset questions when AI providers are unavailable."""
        q = (user_query or "").lower()
        total = int(len(df))

        lookup = self._try_value_lookup(df, user_query)
        if lookup:
            return lookup

        if self._looks_like_correlation_query(user_query):
            return self._build_relationship_summary(df, user_query)

        chart_request = self._parse_chart_request(user_query, df)
        if chart_request is not None:
            return self._build_chart_result(df, user_query, chart_request)

        if self._looks_like_dataset_overview(user_query):
            return self._build_dataset_overview(df, user_query)

        stat = self._try_column_stat(df, user_query)
        if stat:
            return stat

        if any(token in q for token in ("duplicate", "duplicated", "exact duplicate")):
            dup_count = int(df.duplicated().sum())
            unique_rows = total - dup_count
            pct = round((dup_count / total) * 100, 2) if total else 0.0
            answer = (
                f"**Exact duplicate rows:** **{dup_count}** out of **{total}** total rows "
                f"({pct}% duplicates).\n\n"
                f"- Unique rows: **{unique_rows}**\n"
                f"- Duplicate rows: **{dup_count}**"
            )
            return {
                "answer": answer,
                "chart_type": "bar",
                "chart_title": "Duplicate vs Unique Rows",
                "chart_data": {
                    "labels": ["Unique rows", "Duplicate rows"],
                    "values": [unique_rows, dup_count],
                    "colors": ["#10B981", "#EF4444"],
                },
                "chart_image_base64": None,
            }

        if any(token in q for token in ("missing", "null", "na value", "empty value")):
            missing_total = int(df.isnull().sum().sum())
            answer = f"**Total missing values:** **{missing_total}** across **{df.shape[1]}** columns."
            return {
                "answer": answer,
                "chart_type": "bar",
                "chart_title": "Missing Values by Column",
                "chart_data": {
                    "labels": [str(c) for c in df.columns[:10]],
                    "values": [int(df[c].isnull().sum()) for c in df.columns[:10]],
                },
                "chart_image_base64": None,
            }

        if any(token in q for token in ("how many rows", "row count", "number of rows", "total rows", "summarize", "summary")):
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            lines = [f"**Total rows:** **{total}**", f"**Total columns:** **{df.shape[1]}**"]
            if numeric_cols:
                for col in numeric_cols[:3]:
                    lines.append(f"- **{col}** — min: `{df[col].min()}`, max: `{df[col].max()}`, mean: `{round(float(df[col].mean()), 2)}`")
            return {"answer": "\n".join(lines), **EMPTY_CHART_RESULT}

        filtered = self._try_filter_count(df, user_query)
        if filtered:
            return filtered

        unique_vals = self._try_unique_values(df, user_query)
        if unique_vals:
            return unique_vals

        return None

    def _normalize_result(self, result: dict) -> dict:
        """Ensure consistent chart keys and support multi-chart responses."""
        if not isinstance(result, dict):
            raise ValueError("Analysis function must return a dict")

        result.setdefault("chart_type", None)
        result.setdefault("chart_title", None)
        result.setdefault("chart_data", None)
        result.setdefault("chart_image_base64", None)

        charts = result.get("charts")
        if isinstance(charts, list) and charts:
            first = charts[0] if isinstance(charts[0], dict) else {}
            result["chart_type"] = result.get("chart_type") or first.get("chart_type")
            result["chart_title"] = result.get("chart_title") or first.get("title") or first.get("chart_title")
            result["chart_data"] = result.get("chart_data") or first.get("chart_data")
            result["chart_image_base64"] = result.get("chart_image_base64") or first.get("chart_image_base64")
        else:
            result["charts"] = []

        result = self._clean_numpy_types(result)
        if "charts" not in result or not isinstance(result["charts"], list):
            result["charts"] = []
        return result

    def _looks_like_dataset_overview(self, prompt: str) -> bool:
        lowered = (prompt or "").lower()
        overview_tokens = ["analyze this dataset", "what do you see", "dataset overview", "profile this dataset", "summarize the dataset", "explore the data", "inspect this data"]
        return any(token in lowered for token in overview_tokens)

    def _looks_like_correlation_query(self, query: str) -> bool:
        """Detect questions about column relationships / correlations (not pairwise scatter)."""
        q = (query or "").lower()
        if "scatter" in q or re.search(r"\bvs\.?\b", q):
            return False
        if any(token in q for token in ("correlation", "correlate", "correlation matrix")):
            return True
        if any(token in q for token in ("relationship", "column relation", "columns relate")):
            return True
        if "relation" in q and ("column" in q or "columns" in q):
            return True
        if "relate" in q and ("column" in q or "columns" in q):
            return True
        if "heatmap" in q and ("correlation" in q or "column" in q):
            return True
        return False

    def _augment_correlation_chart(self, result: dict, df: pd.DataFrame, user_query: str) -> dict:
        """Ensure correlation questions always return a heatmap when AI omitted a chart."""
        if not self._looks_like_correlation_query(user_query):
            return result
        if result.get("chart_type") or result.get("chart_image_base64"):
            return result
        charts = result.get("charts") or []
        if any(isinstance(c, dict) and (c.get("chart_type") or c.get("chart_image_base64")) for c in charts):
            return result
        rel = self._build_relationship_summary(df, user_query)
        result["chart_type"] = rel.get("chart_type")
        result["chart_title"] = rel.get("chart_title")
        result["chart_data"] = rel.get("chart_data")
        result["chart_image_base64"] = rel.get("chart_image_base64")
        if rel.get("relationship_summary"):
            result["relationship_summary"] = rel["relationship_summary"]
        return result

    def _extract_column_names(self, query: str, columns):
        found = []
        lower_map = {str(c).lower(): c for c in columns}
        for name in sorted(lower_map, key=len, reverse=True):
            if name in query.lower():
                found.append(lower_map[name])
        return found

    def _parse_chart_request(self, user_query: str, df: pd.DataFrame):
        if not user_query:
            return None
        query_lower = user_query.lower()
        interactive = any(word in query_lower for word in ["tooltip", "tooltips", "interactive", "hover", "hoverable"])

        chart_type = None
        if any(word in query_lower for word in ["scatter"]) or (
            re.search(r"\bvs\.?\b", query_lower) and not self._looks_like_correlation_query(user_query)
        ):
            chart_type = "scatter"
        elif self._looks_like_correlation_query(user_query) or any(
            word in query_lower for word in ["correlation heatmap", "heatmap", "matrix"]
        ):
            chart_type = "heatmap_plotly"
        elif any(word in query_lower for word in ["horizontal bar", "barh", "horizontal"]):
            chart_type = "barh"
        elif any(word in query_lower for word in ["donut", "ring"]):
            chart_type = "donut"
        elif any(word in query_lower for word in ["area", "area chart"]):
            chart_type = "area"
        elif any(word in query_lower for word in ["pie", "share", "distribution"]):
            chart_type = "pie"
        elif any(word in query_lower for word in ["line", "trend", "time series", "over time"]):
            chart_type = "line"
        elif any(word in query_lower for word in ["bar chart", "bar", "top", "by category", "count by"]):
            chart_type = "bar"

        if chart_type is None:
            return None

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        cat_cols = df.select_dtypes(exclude=[np.number]).columns.tolist()
        columns_found = self._extract_column_names(user_query, df.columns)

        if chart_type == "scatter":
            x_col = None
            y_col = None
            for candidate in columns_found:
                if candidate in numeric_cols and x_col is None:
                    x_col = candidate
                elif candidate in numeric_cols and y_col is None:
                    y_col = candidate
            if x_col is None and len(numeric_cols) >= 2:
                x_col, y_col = numeric_cols[0], numeric_cols[1]
            elif x_col is None and len(numeric_cols) >= 1:
                x_col, y_col = numeric_cols[0], numeric_cols[0]
            return {
                "chart_type": "scatter",
                "chart_title": f"{x_col or 'X'} vs {y_col or 'Y'}",
                "x_col": x_col,
                "y_col": y_col,
                "interactive": interactive,
            }

        if chart_type == "heatmap_plotly":
            target = numeric_cols if numeric_cols else df.columns.tolist()
            return {"chart_type": "heatmap_plotly", "chart_title": "Column Correlation Heatmap", "columns": target[:min(10, len(target))], "interactive": interactive}

        if chart_type == "barh":
            if columns_found:
                x_col = next((c for c in columns_found if c in numeric_cols), None) or (numeric_cols[0] if numeric_cols else None)
                y_col = next((c for c in columns_found if c in cat_cols), None) or (cat_cols[0] if cat_cols else None)
            else:
                x_col = numeric_cols[0] if numeric_cols else None
                y_col = cat_cols[0] if cat_cols else None
            return {"chart_type": "barh", "chart_title": f"{x_col or 'Value'} by {y_col or 'Category'}", "x_col": x_col, "y_col": y_col, "interactive": interactive}

        if chart_type in ["pie", "donut"]:
            x_col = next((c for c in columns_found if c in cat_cols), None) or (cat_cols[0] if cat_cols else None)
            y_col = next((c for c in columns_found if c in numeric_cols), None) or (numeric_cols[0] if numeric_cols else None)
            if x_col is None and y_col is None:
                x_col = df.columns[0]
                y_col = df.columns[0]
            return {"chart_type": chart_type, "chart_title": f"{y_col or 'Metric'} by {x_col or 'Category'}", "x_col": x_col, "y_col": y_col, "interactive": interactive}

        if chart_type in ["line", "area"]:
            date_like = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c]) or str(df[c].dtype).startswith('datetime') or c.lower().endswith('date') or c.lower().endswith('time')]
            x_col = next((c for c in columns_found if c in df.columns), None) or (date_like[0] if date_like else (df.columns[0] if len(df.columns) > 0 else None))
            y_col = next((c for c in columns_found if c in numeric_cols), None) or (numeric_cols[0] if numeric_cols else None)
            return {"chart_type": chart_type, "chart_title": f"{y_col or 'Value'} by {x_col or 'Period'}", "x_col": x_col, "y_col": y_col, "interactive": interactive}

        x_col = next((c for c in columns_found if c in cat_cols), None) or (cat_cols[0] if cat_cols else None)
        y_col = next((c for c in columns_found if c in numeric_cols), None) or (numeric_cols[0] if numeric_cols else None)
        if x_col is None and y_col is None:
            x_col = df.columns[0]
            y_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
        return {"chart_type": "bar", "chart_title": f"{y_col or 'Value'} by {x_col or 'Category'}", "x_col": x_col, "y_col": y_col, "interactive": interactive}

    def _generate_quality_observations(self, df: pd.DataFrame):
        observations = []
        missing_total = int(df.isnull().sum().sum())
        if missing_total:
            observations.append(f"There are {missing_total} missing values spread across the dataset, which is worth checking before drawing conclusions.")
        duplicate_count = int(df.duplicated().sum())
        if duplicate_count:
            observations.append(f"{duplicate_count} duplicate row(s) were detected, so it may be useful to verify if the data source contains repeated records.")
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            for col in numeric_cols[:3]:
                s = df[col].dropna()
                if s.empty:
                    continue
                q1 = s.quantile(0.25)
                q3 = s.quantile(0.75)
                iqr = q3 - q1
                if iqr and (s.max() - s.min()) > 3 * iqr:
                    observations.append(f"{col} appears to have a wider spread than typical, suggesting a possible outlier or skewed threshold effect.")
                    break
        cat_cols = df.select_dtypes(exclude=[np.number]).columns.tolist()
        if cat_cols:
            top = df[cat_cols[0]].value_counts().head(3).to_dict() if not df.empty else {}
            if top:
                top_label = next(iter(top))
                top_count = next(iter(top.values()))
                observations.append(f"The most common value in {cat_cols[0]} is {top_label} with {top_count} records, indicating the strongest concentration in that category.")
        return observations

    def _build_dataset_overview(self, df: pd.DataFrame, prompt: str):
        row_count = int(df.shape[0])
        col_count = int(df.shape[1])
        duplicate_count = int(df.duplicated().sum())
        missing_total = int(df.isnull().sum().sum())
        missing_by_column = []
        for col in df.columns:
            count = int(df[col].isnull().sum())
            pct = round(float((count / len(df)) * 100), 2) if len(df) else 0.0
            missing_by_column.append((str(col), count, pct))
        observations = self._generate_quality_observations(df)
        summary_lines = [
            f"**Dataset overview:** {row_count} rows and {col_count} columns.",
            f"**Duplicate rows:** {duplicate_count}",
            f"**Missing values overall:** {missing_total}",
        ]
        if missing_by_column:
            top_cols = sorted(missing_by_column, key=lambda x: x[1], reverse=True)[:5]
            summary_lines.append("**Most missing columns:** " + ", ".join(f"{name} ({count}, {pct}%)" for name, count, pct in top_cols))
        summary_lines.extend(f"- {obs}" for obs in observations)
        answer = "\n".join(summary_lines)
        return {
            "answer": answer,
            "chart_type": None,
            "chart_title": None,
            "chart_data": None,
            "chart_image_base64": None,
            "dataset_summary": {"row_count": row_count, "col_count": col_count, "duplicate_count": duplicate_count, "missing_total": missing_total, "missing_by_column": [{"column": name, "count": count, "pct": pct} for name, count, pct in missing_by_column]},
        }

    def _build_relationship_summary(self, df: pd.DataFrame, prompt: str = ""):
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        corr = df[numeric_cols].corr(numeric_only=True) if numeric_cols else pd.DataFrame()
        pairs = []
        if not corr.empty:
            for i, left in enumerate(corr.columns):
                for j in range(i + 1, len(corr.columns)):
                    right = corr.columns[j]
                    val = corr.iloc[i, j]
                    if pd.notna(val):
                        pairs.append({"left": left, "right": right, "correlation": float(val), "strength": round(abs(float(val)), 4)})
        pairs = sorted(pairs, key=lambda item: item["strength"], reverse=True)[:6]

        def _strength_label(value: float) -> str:
            strength = abs(value)
            if strength >= 0.7:
                return "strong"
            if strength >= 0.4:
                return "moderate"
            return "weak"

        relationship_lines = [
            f"- **{item['left']}** ↔ **{item['right']}**: `{item['correlation']:.3f}` ({_strength_label(item['correlation'])})"
            for item in pairs
        ] or ["- No numeric columns available to compute correlations."]
        summary = "\n".join([
            "**Column correlation analysis**",
            f"Analyzed **{len(numeric_cols)}** numeric column(s). Strongest relationships:",
            *relationship_lines,
            "",
            "*Correlation heatmap generated below — green = positive, red = negative.*",
        ])
        chart_data = None
        chart_type = None
        charts = []
        if numeric_cols and not corr.empty:
            chart_type = "heatmap_plotly"
            chart_data = {
                "z": corr.round(3).fillna(0).values.tolist(),
                "x": corr.columns.tolist(),
                "y": corr.columns.tolist(),
                "colorscale": "RdYlGn",
            }
            if pairs:
                top = pairs[0]
                charts.append({
                    "title": f"{top['left']} vs {top['right']} (r={top['correlation']:.2f})",
                    "chart_type": "scatter",
                    "chart_data": {
                        "x": df[top["left"]].fillna(0).tolist(),
                        "y": df[top["right"]].fillna(0).tolist(),
                        "x_label": str(top["left"]),
                        "y_label": str(top["right"]),
                        "colors": ["#06B6D4" for _ in range(len(df))],
                    },
                    "chart_image_base64": None,
                })
        return {
            "answer": summary,
            "chart_type": chart_type,
            "chart_title": "Column Correlation Heatmap" if chart_type else None,
            "chart_data": chart_data,
            "chart_image_base64": None,
            "charts": charts,
            "relationship_summary": {"pairs": pairs},
        }

    def _build_chart_result(self, df: pd.DataFrame, user_query: str, req: dict):
        chart_type = req["chart_type"]
        x_col = req.get("x_col")
        y_col = req.get("y_col")
        interactive = bool(req.get("interactive"))

        if chart_type == "scatter":
            if x_col and y_col and x_col != y_col:
                chart_data = {"x": df[x_col].fillna(0).tolist(), "y": df[y_col].fillna(0).tolist(), "x_label": str(x_col), "y_label": str(y_col), "colors": ["#06B6D4" for _ in range(len(df))]}
                return {"answer": f"**Scatter plot:** comparing **{x_col}** and **{y_col}**.", "chart_type": "scatter" if interactive else None, "chart_title": req["chart_title"], "chart_data": chart_data if interactive else None, "chart_image_base64": self._render_static_chart(df, chart_type, req) if not interactive else None}

        if chart_type == "heatmap_plotly":
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            corr = df[numeric_cols].corr(numeric_only=True) if numeric_cols else pd.DataFrame()
            chart_data = {"z": corr.fillna(0).values.tolist(), "x": corr.columns.tolist(), "y": corr.columns.tolist(), "colorscale": "RdYlGn"}
            return {"answer": "**Correlation heatmap:** showing the strongest numeric relationships in the dataset.", "chart_type": "heatmap_plotly" if interactive else None, "chart_title": req["chart_title"], "chart_data": chart_data if interactive else None, "chart_image_base64": self._render_static_chart(df, "heatmap", req) if not interactive else None}

        if chart_type == "barh":
            if x_col and y_col:
                grouped = df.groupby(y_col, dropna=False)[x_col].sum().sort_values(ascending=False).head(10)
            else:
                grouped = df.iloc[:, 0].value_counts().head(10)
            chart_data = {"labels": [str(v) for v in grouped.index.tolist()], "values": [float(v) for v in grouped.values.tolist()], "x_label": str(x_col or "Value"), "y_label": str(y_col or "Category"), "orientation": "h", "colors": ["#06B6D4", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#F97316", "#14B8A6"]}
            return {"answer": f"**Horizontal bar chart:** ranking {x_col or 'values'} by {y_col or 'category'}.", "chart_type": "barh" if interactive else None, "chart_title": req["chart_title"], "chart_data": chart_data if interactive else None, "chart_image_base64": self._render_static_chart(df, "barh", req) if not interactive else None}

        if chart_type in ["pie", "donut"]:
            if x_col and y_col:
                grouped = df.groupby(x_col, dropna=False)[y_col].sum().sort_values(ascending=False).head(8)
            else:
                grouped = df.iloc[:, 0].value_counts().head(8)
            chart_data = {"labels": [str(v) for v in grouped.index.tolist()], "values": [float(v) for v in grouped.values.tolist()], "x_label": str(x_col or "Category"), "y_label": str(y_col or "Value"), "colors": ["#06B6D4", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#F97316", "#14B8A6"]}
            return {"answer": f"**{chart_type.upper()} chart:** showing the composition of {x_col or 'categories'}.", "chart_type": "pie" if interactive else None, "chart_title": req["chart_title"], "chart_data": chart_data if interactive else None, "chart_image_base64": self._render_static_chart(df, "donut" if chart_type == "donut" else "pie", req) if not interactive else None}

        if chart_type in ["line", "area"]:
            if x_col and y_col:
                try:
                    if pd.api.types.is_datetime64_any_dtype(df[x_col]) or str(df[x_col].dtype).lower().startswith('datetime'):
                        grouped = df.groupby(x_col, dropna=False)[y_col].sum()
                    else:
                        grouped = df.groupby(x_col, dropna=False)[y_col].sum().sort_index()
                except Exception:
                    grouped = df[[x_col, y_col]].dropna().head(15)
            else:
                grouped = df.iloc[:, 0].head(15)
            labels = [str(v) for v in grouped.index.tolist()]
            values = [float(v) for v in grouped.tolist()]
            chart_data = {"labels": labels, "values": values, "x_label": str(x_col or "Period"), "y_label": str(y_col or "Value"), "colors": ["#06B6D4", "#10B981"]}
            return {"answer": f"**{chart_type.upper()} chart:** reviewing the trend of **{y_col or 'value'}** over **{x_col or 'time'}**.", "chart_type": "line" if interactive else None, "chart_title": req["chart_title"], "chart_data": chart_data if interactive else None, "chart_image_base64": self._render_static_chart(df, chart_type, req) if not interactive else None}

        if x_col and y_col:
            grouped = df.groupby(x_col, dropna=False)[y_col].sum().sort_values(ascending=False).head(10)
            chart_data = {"labels": [str(v) for v in grouped.index.tolist()], "values": [float(v) for v in grouped.values.tolist()], "x_label": str(x_col), "y_label": str(y_col), "colors": ["#06B6D4", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#F97316", "#14B8A6"]}
            return {"answer": f"**Bar chart:** comparing **{y_col}** across **{x_col}**.", "chart_type": "bar" if interactive else None, "chart_title": req["chart_title"], "chart_data": chart_data if interactive else None, "chart_image_base64": self._render_static_chart(df, "bar", req) if not interactive else None}

        return {"answer": "**Chart request processed:** the dataset has been summarized for the requested visualization.", "chart_type": None, "chart_title": None, "chart_data": None, "chart_image_base64": None}

    def _render_static_chart(self, df: pd.DataFrame, chart_type: str, req: dict):
        plt.style.use('dark_background')
        # Explicitly configure dark background properties for light text visibility
        plt.rcParams['figure.facecolor'] = '#0d1117'
        plt.rcParams['axes.facecolor'] = '#161b22'
        plt.rcParams['text.color'] = '#e2e8f0'
        plt.rcParams['axes.labelcolor'] = '#e2e8f0'
        plt.rcParams['xtick.color'] = '#cbd5e1'
        plt.rcParams['ytick.color'] = '#cbd5e1'
        plt.rcParams['grid.color'] = '#30363d'
        
        # Configure seaborn style without overriding text/axis color
        sns.set_style('darkgrid', {
            'figure.facecolor': '#0d1117',
            'axes.facecolor': '#161b22',
            'text.color': '#e2e8f0',
            'axes.labelcolor': '#e2e8f0',
            'xtick.color': '#cbd5e1',
            'ytick.color': '#cbd5e1',
            'grid.color': '#30363d'
        })
        color_palette = ['#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#F97316', '#14B8A6']
        try:
            fig, ax = plt.subplots(figsize=(8, 5))
            if chart_type == 'bar':
                x_col = req.get('x_col'); y_col = req.get('y_col')
                if x_col and y_col:
                    grouped = df.groupby(x_col, dropna=False)[y_col].sum().sort_values(ascending=False).head(10)
                    ax.bar(grouped.index.astype(str), grouped.values, color=sns.color_palette(color_palette, n_colors=len(grouped)))
                    ax.set_xlabel(x_col)
                    ax.set_ylabel(y_col)
                    ax.set_title(req.get('chart_title', f'{y_col} by {x_col}'))
            elif chart_type == 'barh':
                x_col = req.get('x_col'); y_col = req.get('y_col')
                if x_col and y_col:
                    grouped = df.groupby(y_col, dropna=False)[x_col].sum().sort_values(ascending=False).head(10)
                    ax.barh(grouped.index.astype(str), grouped.values, color=sns.color_palette(color_palette, n_colors=len(grouped)))
                    ax.set_xlabel(x_col)
                    ax.set_ylabel(y_col)
                    ax.set_title(req.get('chart_title', f'{x_col} by {y_col}'))
            elif chart_type in ['line', 'area']:
                x_col = req.get('x_col'); y_col = req.get('y_col')
                if x_col and y_col:
                    series = df[[x_col, y_col]].dropna()
                    if chart_type == 'area':
                        ax.fill_between(series[x_col].astype(str), series[y_col], color='#10B981', alpha=0.45)
                    ax.plot(series[x_col].astype(str), series[y_col], color='#06B6D4', linewidth=2.5, marker='o')
                    ax.set_xlabel(x_col)
                    ax.set_ylabel(y_col)
                    ax.set_title(req.get('chart_title', f'{y_col} by {x_col}'))
            elif chart_type == 'scatter':
                x_col = req.get('x_col'); y_col = req.get('y_col')
                if x_col and y_col:
                    series = df[[x_col, y_col]].dropna()
                    ax.scatter(series[x_col], series[y_col], c=series[y_col], cmap='viridis', alpha=0.8)
                    ax.set_xlabel(x_col)
                    ax.set_ylabel(y_col)
                    ax.set_title(req.get('chart_title', f'{y_col} vs {x_col}'))
            elif chart_type == 'pie' or chart_type == 'donut':
                x_col = req.get('x_col'); y_col = req.get('y_col')
                if x_col and y_col:
                    grouped = df.groupby(x_col, dropna=False)[y_col].sum().sort_values(ascending=False).head(8)
                    wedges, texts = ax.pie(grouped.values, labels=grouped.index.astype(str), colors=sns.color_palette(color_palette, n_colors=len(grouped)), autopct='%1.1f%%')
                    if chart_type == 'donut':
                        centre_circle = plt.Circle((0, 0), 0.55, fc='black')
                        ax.add_artist(centre_circle)
                    ax.set_title(req.get('chart_title', f'{y_col} by {x_col}'))
            elif chart_type == 'heatmap':
                numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
                if numeric_cols:
                    corr = df[numeric_cols].corr(numeric_only=True)
                    sns.heatmap(corr, cmap='RdYlGn', annot=True, fmt='.2f', ax=ax)
                    ax.set_title(req.get('chart_title', 'Correlation Heatmap'))
            ax.tick_params(axis='x', rotation=45)
            fig.tight_layout()
            return _save_plot_to_base64()
        except Exception:
            return None

    def _generate_schema_summary(self, df: pd.DataFrame) -> str:
        """Creates a rich metadata block describing columns, types, sample values, and stats."""
        summary = []
        summary.append(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
        summary.append("Columns detail (use EXACT column names in code):")
        for col in df.columns:
            dtype = df[col].dtype
            null_count = df[col].isnull().sum()
            sample_vals = df[col].dropna().head(5).tolist()
            unique_count = df[col].nunique()
            is_date_like = False
            if dtype == object:
                try:
                    test = pd.to_datetime(df[col].dropna().head(20), errors='coerce', infer_datetime_format=True)
                    if test.notna().sum() > 10:
                        is_date_like = True
                except Exception:
                    pass
            summary.append(
                f"  - '{col}': dtype={dtype}, nulls={null_count}, unique={unique_count}, "
                f"date_like={is_date_like}, samples={sample_vals[:3]}"
            )

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            summary.append(f"\nNumeric columns: {numeric_cols}")
            summary.append("Stats (describe):")
            summary.append(df[numeric_cols].describe().round(2).to_string())

        cat_cols = df.select_dtypes(include=['object']).columns.tolist()
        if cat_cols:
            summary.append(f"\nCategorical columns: {cat_cols}")
            for col in cat_cols[:5]:
                top_vals = df[col].value_counts().head(5).to_dict()
                summary.append(f"  - '{col}' top values: {top_vals}")

        return "\n".join(summary)

    def _extract_python_code(self, text: str) -> str:
        """Parses python blocks from the assistant response."""
        pattern = r"```(?:python)?\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1)
        return text.strip()

    def _build_analysis_sandbox(self, df: pd.DataFrame) -> dict:
        """Build execution sandbox with all data-science libraries the chatbot may use."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        import seaborn as sns

        sandbox = {
            "df": df.copy(),
            "pd": pd,
            "np": np,
            "plt": plt,
            "mticker": mticker,
            "sns": sns,
            "io": io,
            "json": json,
            "re": re,
            "base64": base64,
            "save_plot_to_base64": _save_plot_to_base64,
        }

        import math
        import datetime as dt_module
        from datetime import datetime, timedelta
        sandbox["math"] = math
        sandbox["datetime"] = dt_module
        sandbox["timedelta"] = timedelta
        sandbox["dt"] = datetime

        try:
            import sklearn
            from sklearn import preprocessing, cluster, decomposition, linear_model, metrics, model_selection, ensemble
            sandbox["sklearn"] = sklearn
            sandbox["preprocessing"] = preprocessing
            sandbox["cluster"] = cluster
            sandbox["decomposition"] = decomposition
            sandbox["linear_model"] = linear_model
            sandbox["metrics"] = metrics
            sandbox["model_selection"] = model_selection
            sandbox["ensemble"] = ensemble
        except ImportError:
            pass

        try:
            import scipy
            import scipy.stats as stats
            sandbox["scipy"] = scipy
            sandbox["stats"] = stats
        except ImportError:
            pass

        try:
            import statsmodels.api as sm
            sandbox["sm"] = sm
            sandbox["statsmodels"] = __import__("statsmodels")
        except ImportError:
            pass

        return sandbox

    def _execute_code(self, code_str: str, df: pd.DataFrame) -> dict:
        """Safely executes the python function with a rich sandbox."""
        sandbox = self._build_analysis_sandbox(df)

        exec(code_str, sandbox)

        if "analyze" not in sandbox:
            raise ValueError("The generated code did not contain the 'analyze' function.")

        result = sandbox["analyze"](sandbox["df"])
        result = self._clean_numpy_types(result)
        return result

    def _clean_numpy_types(self, obj):
        """Recursively converts numpy values and NaNs/Infs to JSON-safe types."""
        if isinstance(obj, dict):
            return {k: self._clean_numpy_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_numpy_types(x) for x in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return None if (np.isnan(obj) or np.isinf(obj)) else float(obj)
        elif isinstance(obj, float):
            return None if (np.isnan(obj) or np.isinf(obj)) else obj
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return self._clean_numpy_types(obj.tolist())
        else:
            try:
                if pd.isna(obj):
                    return None
            except Exception:
                pass
        return obj

    def _mock_query_data(self, df: pd.DataFrame, user_query: str) -> dict:
        """A basic heuristic offline fallback."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = df.select_dtypes(exclude=[np.number]).columns.tolist()
        query_lower = user_query.lower()

        chart_type = None
        chart_title = None
        chart_data = None

        if any(k in query_lower for k in ["bar", "chart", "plot", "graph", "top"]):
            if numeric_cols and categorical_cols:
                cat, num = categorical_cols[0], numeric_cols[0]
                grouped = df.groupby(cat)[num].sum().nlargest(10).reset_index()
                chart_type = "bar"
                chart_title = f"Top {num} by {cat}"
                chart_data = {
                    "labels": grouped[cat].astype(str).tolist(),
                    "values": [float(x) for x in grouped[num].tolist()],
                    "colors": ['#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#F97316', '#14B8A6', '#A78BFA', '#FB7185']
                }

        answer = f"""### ⚠️ MOCK MODE (No API Key)
*Connect a real Groq API key to get full analytical responses.*

**Dataset:** {df.shape[0]} rows × {df.shape[1]} columns
**Your query:** *"{user_query}"*

**Available columns:** {', '.join([f'`{c}`' for c in df.columns[:10]])}
"""
        return {
            "answer": answer,
            "chart_type": chart_type,
            "chart_title": chart_title,
            "chart_data": chart_data,
            "chart_image_base64": None
        }


groq_service = GroqService()
