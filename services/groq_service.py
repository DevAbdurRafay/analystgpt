import os
import re
import io
import base64
import pandas as pd
import numpy as np
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")


def _save_plot_to_base64():
    """Utility injected into sandbox: saves the current matplotlib figure to a base64 PNG string."""
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
        self.model = "llama-3.3-70b-versatile"
        if self.api_key:
            self.client = Groq(api_key=self.api_key)
        else:
            self.client = None

    def query_data(self, df: pd.DataFrame, user_query: str) -> dict:
        """Analyzes a dataframe based on ANY user query."""
        if not self.client:
            load_dotenv(override=True)
            self.api_key = os.getenv("GROQ_API_KEY")
            if self.api_key:
                try:
                    self.client = Groq(api_key=self.api_key)
                except Exception:
                    pass

        if not self.client:
            return self._mock_query_data(df, user_query)

        schema_summary = self._generate_schema_summary(df)

        system_prompt = f"""You are AnalystGPT — the world's most advanced data analyst AI assistant. You have expertise in:
- Pandas, NumPy, statistics, and data storytelling
- Time intelligence (Previous Month, Previous Quarter, Previous Year, YoY growth, MoM change, Rolling averages)
- DAX-equivalent calculations implemented in Python/Pandas
- Advanced visualizations using Matplotlib, Seaborn, AND Plotly-compatible data
- Correlation analysis, distribution analysis, outlier detection, regression analysis
- Creating ANY type of chart the user asks for

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

MATPLOTLIB/SEABORN CHART GUIDE (use for: heatmaps, pairplots, horizontal bars, violin plots, box plots, custom correlation matrices, multi-series with custom colors):
```python
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

# Always use dark theme:
plt.style.use('dark_background')
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
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                model=self.model,
                temperature=0.05,
                max_tokens=4000
            )

            response_text = chat_completion.choices[0].message.content
            cleaned_code = self._extract_python_code(response_text)

            result = self._execute_code(cleaned_code, df)
            # Ensure the new key always exists
            if "chart_image_base64" not in result:
                result["chart_image_base64"] = None
            return result

        except Exception as e:
            return {
                "answer": f"### Execution Error\nAn error occurred: \n`{str(e)}`.\n\n*Please try rephrasing your question.*",
                "chart_type": None,
                "chart_title": None,
                "chart_data": None,
                "chart_image_base64": None
            }

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

    def _execute_code(self, code_str: str, df: pd.DataFrame) -> dict:
        """Safely executes the python function with a rich sandbox."""
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
        import seaborn as sns

        sandbox = {
            "df": df.copy(),
            "pd": pd,
            "np": np,
            "plt": plt,
            "sns": sns,
            "io": io,
            "base64": base64,
            "save_plot_to_base64": _save_plot_to_base64,
        }

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
