import re
import pandas as pd
import numpy as np


class DataCleaner:
    @staticmethod
    def get_diagnostics(df: pd.DataFrame) -> dict:
        """Gathers comprehensive summary diagnostics and preview of the dataframe."""
        row_count, col_count = df.shape

        # Count null values
        null_counts = {str(k): int(v) for k, v in df.isnull().sum().to_dict().items()}
        missing_value_total = int(df.isnull().sum().sum())
        missing_by_column = {}
        for col in df.columns:
            count = int(df[col].isnull().sum())
            pct = round(float((count / len(df)) * 100), 2) if len(df) else 0.0
            missing_by_column[str(col)] = {"count": count, "pct": pct}

        # Columns and types
        dtypes = {str(k): str(v) for k, v in df.dtypes.to_dict().items()}
        columns = list(df.columns)

        # Duplicate count
        duplicate_count = int(df.duplicated().sum())

        # Per-column detailed profile
        column_profiles = {}
        for col in df.columns:
            col_str = str(col)
            s = df[col]
            profile = {
                "dtype": str(s.dtype),
                "nulls": int(s.isnull().sum()),
                "null_pct": round(float(s.isnull().mean() * 100), 2),
                "unique": int(s.nunique()),
            }
            if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
                desc = s.describe()
                profile["min"] = _safe_float(desc.get("min"))
                profile["max"] = _safe_float(desc.get("max"))
                profile["mean"] = _safe_float(desc.get("mean"))
                profile["median"] = _safe_float(s.median())
                profile["std"] = _safe_float(desc.get("std"))
                profile["q1"] = _safe_float(desc.get("25%"))
                profile["q3"] = _safe_float(desc.get("75%"))
                # IQR outlier count
                q1, q3 = s.quantile(0.25), s.quantile(0.75)
                iqr = q3 - q1
                outlier_count = int(((s < (q1 - 1.5 * iqr)) | (s > (q3 + 1.5 * iqr))).sum())
                profile["outlier_count"] = outlier_count
            elif pd.api.types.is_datetime64_any_dtype(s):
                profile["min_date"] = str(s.min()) if not pd.isna(s.min()) else None
                profile["max_date"] = str(s.max()) if not pd.isna(s.max()) else None
                profile["date_range_days"] = int((s.max() - s.min()).days) if s.notna().any() else None
            else:
                top_vals = s.value_counts().head(5).to_dict()
                profile["top_values"] = {str(k): int(v) for k, v in top_vals.items()}

            column_profiles[col_str] = profile

        # Summary statistics for numeric columns
        numeric_df = df.select_dtypes(include=[np.number]).select_dtypes(exclude=[bool, 'bool', 'boolean'])
        summary_stats = {}
        if not numeric_df.empty:
            stats = numeric_df.describe().to_dict()
            for col, col_stats in stats.items():
                summary_stats[str(col)] = {
                    str(stat): (None if pd.isna(val) or np.isinf(val) else float(val))
                    for stat, val in col_stats.items()
                }

        # Safe head preview (10 rows)
        preview_df = df.head(10)
        preview_data = []
        for _, row in preview_df.iterrows():
            row_dict = {}
            for col in df.columns:
                val = row[col]
                try:
                    if pd.isna(val):
                        row_dict[str(col)] = None
                        continue
                except TypeError:
                    pass
                if isinstance(val, (float, np.float64)):
                    row_dict[str(col)] = None if (np.isnan(val) or np.isinf(val)) else float(val)
                elif isinstance(val, (int, np.int64, np.integer)):
                    row_dict[str(col)] = int(val)
                elif isinstance(val, pd.Timestamp):
                    row_dict[str(col)] = val.isoformat()
                else:
                    row_dict[str(col)] = str(val)
            preview_data.append(row_dict)

        return {
            "row_count": int(row_count),
            "col_count": int(col_count),
            "duplicate_count": duplicate_count,
            "missing_value_total": missing_value_total,
            "missing_by_column": missing_by_column,
            "null_counts": null_counts,
            "dtypes": dtypes,
            "columns": columns,
            "column_profiles": column_profiles,
            "summary_stats": summary_stats,
            "preview": preview_data,
        }

    @staticmethod
    def clean_data(df: pd.DataFrame, options: dict | None = None) -> pd.DataFrame:
        """Cleans the dataframe according to selected pre-cleaning normalization steps."""
        options = options or {}
        cleaned_df = df.copy()

        def _enabled(key: str, default: bool = True) -> bool:
            return bool(options.get(key, default))

        # a. NORMALIZE COLUMN HEADERS
        if _enabled("header_formatting"):
            new_columns = []
            for col in cleaned_df.columns:
                formatted = str(col).strip().lower()
                formatted = re.sub(r'[\s\.\-]+', '_', formatted)
                while "__" in formatted:
                    formatted = formatted.replace("__", "_")
                formatted = formatted.strip("_")
                new_columns.append(formatted)
            cleaned_df.columns = new_columns

        # b. TEXT FORMATTING (all string/object columns)
        if _enabled("text_formatting"):
            acronyms = {"HR", "IBM", "USA", "CEO", "IT"}

            def title_case_with_acronyms(s):
                if not isinstance(s, str):
                    return s
                s = re.sub(r'\s+', ' ', s).strip()

                def replace_word(match):
                    word = match.group(0)
                    clean_word = re.sub(r'[^a-zA-Z0-9]', '', word).upper()
                    if clean_word in acronyms:
                        return word.upper()
                    if len(word) > 0:
                        return word[0].upper() + word[1:].lower()
                    return word

                return re.sub(r'\b[a-zA-Z0-9\']+\b', replace_word, s)

            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    cleaned_df[col] = cleaned_df[col].apply(title_case_with_acronyms)

        # c. DATA TYPE CORRECTION
        if _enabled("type_correction"):
            for col in cleaned_df.columns:
                if pd.api.types.is_bool_dtype(cleaned_df[col]):
                    continue

                if cleaned_df[col].dtype == "object":
                    cleaned_s = cleaned_df[col].astype(str).str.replace(r'[\$\€\£\s,]', '', regex=True).str.replace(r'%$', '', regex=True)
                    numeric_conv = pd.to_numeric(cleaned_s, errors='coerce')
                    non_null_count = cleaned_df[col].notna().sum()
                    if non_null_count > 0 and numeric_conv.notna().sum() / non_null_count > 0.8:
                        cleaned_df[col] = numeric_conv

                if pd.api.types.is_float_dtype(cleaned_df[col]):
                    valid_vals = cleaned_df[col].dropna()
                    if not valid_vals.empty and (valid_vals == valid_vals.round()).all():
                        cleaned_df[col] = cleaned_df[col].astype("Int64")

        # d. TYPE CONVERSION & DATES
        if _enabled("parse_dates"):
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    try:
                        test_dates = pd.to_datetime(cleaned_df[col], errors='coerce')
                        non_null_count = cleaned_df[col].notna().sum()
                        if non_null_count > 0 and test_dates.notna().sum() / non_null_count > 0.5:
                            cleaned_df[col] = test_dates
                    except Exception:
                        pass

        # e. Remove control/non-printable characters
        if _enabled("control_chars"):
            def remove_control_chars(val):
                if not isinstance(val, str):
                    return val
                return re.sub(r'[\x00-\x1F\x7F]', '', val)

            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    cleaned_df[col] = cleaned_df[col].apply(remove_control_chars)

        return cleaned_df


def _safe_float(val):
    try:
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return None
        return round(float(val), 4)
    except Exception:
        return None
