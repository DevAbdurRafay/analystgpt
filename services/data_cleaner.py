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
            if pd.api.types.is_numeric_dtype(s):
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
        numeric_df = df.select_dtypes(include=[np.number])
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
            "null_counts": null_counts,
            "dtypes": dtypes,
            "columns": columns,
            "column_profiles": column_profiles,
            "summary_stats": summary_stats,
            "preview": preview_data,
        }

    @staticmethod
    def clean_data(df: pd.DataFrame, options: dict) -> pd.DataFrame:
        """Cleans the dataframe according to the selected options."""
        cleaned_df = df.copy()

        # ── 1. Strip and format column headers ──────────────────────────────
        if options.get("header_formatting", False):
            new_columns = []
            for col in cleaned_df.columns:
                formatted = str(col).strip().lower()
                formatted = formatted.replace(" ", "_").replace(".", "_").replace("-", "_")
                while "__" in formatted:
                    formatted = formatted.replace("__", "_")
                new_columns.append(formatted)
            cleaned_df.columns = new_columns

        # ── 2. Drop selected columns ─────────────────────────────────────────
        cols_to_drop = options.get("drop_columns", [])
        if cols_to_drop:
            existing = [c for c in cols_to_drop if c in cleaned_df.columns]
            if existing:
                cleaned_df = cleaned_df.drop(columns=existing)

        # ── 3. Rename columns ────────────────────────────────────────────────
        rename_map = options.get("rename_columns", {})
        if rename_map:
            cleaned_df = cleaned_df.rename(columns={k: v for k, v in rename_map.items() if k in cleaned_df.columns})

        # ── 4. Trim whitespace from string columns ───────────────────────────
        if options.get("trim_whitespace", False):
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    cleaned_df[col] = cleaned_df[col].str.strip()

        # ── 5. Text case formatting ──────────────────────────────────────────
        text_case = options.get("text_case", "none")
        if text_case != "none":
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    if text_case == "lowercase":
                        cleaned_df[col] = cleaned_df[col].str.lower()
                    elif text_case == "uppercase":
                        cleaned_df[col] = cleaned_df[col].str.upper()
                    elif text_case == "titlecase":
                        cleaned_df[col] = cleaned_df[col].str.title()
                    elif text_case == "sentencecase":
                        cleaned_df[col] = cleaned_df[col].str.capitalize()

        # ── 6. Strip special characters / punctuation ────────────────────────
        strip_mode = options.get("strip_special_chars", "none")
        if strip_mode != "none":
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    if strip_mode == "punctuation":
                        # Remove all punctuation except spaces
                        cleaned_df[col] = cleaned_df[col].str.replace(r'[^\w\s]', '', regex=True)
                    elif strip_mode == "non_ascii":
                        # Remove non-ASCII characters
                        cleaned_df[col] = cleaned_df[col].str.encode('ascii', errors='ignore').str.decode('ascii')
                    elif strip_mode == "digits":
                        # Remove all digits from text columns
                        cleaned_df[col] = cleaned_df[col].str.replace(r'\d', '', regex=True)
                    elif strip_mode == "extra_spaces":
                        # Collapse multiple spaces to single
                        cleaned_df[col] = cleaned_df[col].str.replace(r'\s+', ' ', regex=True).str.strip()

        # ── 7. Parse numbers hidden in string format (e.g. "$1,250.50" → 1250.5) ──
        if options.get("numeric_parsing", False):
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    sample_vals = cleaned_df[col].dropna().head(10).astype(str)
                    if sample_vals.empty:
                        continue
                    is_numeric_like = sample_vals.str.match(
                        r"^\s*[\$\€\£]?\s*-?\s*\d+([,\.]\d+)*\s*\%?\s*$"
                    ).any()
                    if is_numeric_like:
                        try:
                            cleaned_col = cleaned_df[col].astype(str)
                            cleaned_col = cleaned_col.str.replace(r"[\$\€\£\s,]", "", regex=True)
                            is_percent = cleaned_col.str.endswith("%")
                            cleaned_col = cleaned_col.str.rstrip("%")
                            numeric_series = pd.to_numeric(cleaned_col, errors="coerce")
                            if is_percent.any():
                                numeric_series = np.where(is_percent, numeric_series / 100.0, numeric_series)
                            cleaned_df[col] = numeric_series
                        except Exception:
                            pass

        # ── 8. Numeric clipping / bounding ───────────────────────────────────
        clip_std_factor = options.get("clip_numeric_std", None)
        if clip_std_factor:
            try:
                factor = float(clip_std_factor)
                for col in cleaned_df.select_dtypes(include=[np.number]).columns:
                    mean = cleaned_df[col].mean()
                    std = cleaned_df[col].std()
                    if pd.notna(mean) and pd.notna(std) and std > 0:
                        cleaned_df[col] = cleaned_df[col].clip(
                            lower=mean - factor * std,
                            upper=mean + factor * std
                        )
            except (ValueError, TypeError):
                pass

        # ── 9. Auto-parse date columns ───────────────────────────────────────
        if options.get("parse_dates", False):
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    try:
                        test = pd.to_datetime(cleaned_df[col], infer_datetime_format=True, errors='coerce')
                        if test.notna().sum() > len(cleaned_df) * 0.5:
                            cleaned_df[col] = test
                    except Exception:
                        pass

        # ── 10. Date format standardisation ──────────────────────────────────
        date_format_out = options.get("date_format_output", None)
        if date_format_out:
            for col in cleaned_df.columns:
                if pd.api.types.is_datetime64_any_dtype(cleaned_df[col]):
                    try:
                        cleaned_df[col] = cleaned_df[col].dt.strftime(date_format_out)
                    except Exception:
                        pass

        # ── 11. Remove duplicate records ──────────────────────────────────────
        if options.get("remove_duplicates", False):
            cleaned_df = cleaned_df.drop_duplicates()

        # ── 12. Handle Missing Values ─────────────────────────────────────────
        null_handling = options.get("null_handling", "none")
        custom_fill_value = options.get("custom_fill_value", None)

        if null_handling == "drop":
            cleaned_df = cleaned_df.dropna()
        elif null_handling == "fill_mean":
            for col in cleaned_df.columns:
                if cleaned_df[col].isnull().any():
                    if pd.api.types.is_numeric_dtype(cleaned_df[col]):
                        mean_val = cleaned_df[col].mean()
                        cleaned_df[col] = cleaned_df[col].fillna(mean_val if not pd.isna(mean_val) else 0)
                    else:
                        mode_vals = cleaned_df[col].mode()
                        mode_val = mode_vals.iloc[0] if not mode_vals.empty else "Unknown"
                        cleaned_df[col] = cleaned_df[col].fillna(mode_val)
        elif null_handling == "fill_median":
            for col in cleaned_df.columns:
                if cleaned_df[col].isnull().any():
                    if pd.api.types.is_numeric_dtype(cleaned_df[col]):
                        median_val = cleaned_df[col].median()
                        cleaned_df[col] = cleaned_df[col].fillna(median_val if not pd.isna(median_val) else 0)
                    else:
                        mode_vals = cleaned_df[col].mode()
                        mode_val = mode_vals.iloc[0] if not mode_vals.empty else "Unknown"
                        cleaned_df[col] = cleaned_df[col].fillna(mode_val)
        elif null_handling == "fill_zero":
            for col in cleaned_df.columns:
                if cleaned_df[col].isnull().any():
                    if pd.api.types.is_numeric_dtype(cleaned_df[col]):
                        cleaned_df[col] = cleaned_df[col].fillna(0)
                    else:
                        cleaned_df[col] = cleaned_df[col].fillna("Unknown")
        elif null_handling == "fill_custom":
            if custom_fill_value is not None:
                for col in cleaned_df.columns:
                    if cleaned_df[col].isnull().any():
                        if pd.api.types.is_numeric_dtype(cleaned_df[col]):
                            try:
                                cleaned_df[col] = cleaned_df[col].fillna(float(custom_fill_value))
                            except (ValueError, TypeError):
                                cleaned_df[col] = cleaned_df[col].fillna(0)
                        else:
                            cleaned_df[col] = cleaned_df[col].fillna(str(custom_fill_value))
        elif null_handling == "forward_fill":
            cleaned_df = cleaned_df.ffill()
        elif null_handling == "backward_fill":
            cleaned_df = cleaned_df.bfill()
        elif null_handling == "drop_cols_threshold":
            # Drop columns where null % exceeds threshold
            threshold = float(options.get("null_col_threshold", 50)) / 100.0
            cleaned_df = cleaned_df.loc[:, cleaned_df.isnull().mean() <= threshold]

        # ── 13. Remove outliers via IQR method (numeric columns only) ─────────
        if options.get("remove_outliers_iqr", False):
            numeric_cols = cleaned_df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                q1 = cleaned_df[col].quantile(0.25)
                q3 = cleaned_df[col].quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr
                cleaned_df = cleaned_df[(cleaned_df[col].isna()) | ((cleaned_df[col] >= lower) & (cleaned_df[col] <= upper))]

        # ── 14. Cap outliers instead of removing (winsorizing) ────────────────
        if options.get("cap_outliers_iqr", False):
            numeric_cols = cleaned_df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                q1 = cleaned_df[col].quantile(0.25)
                q3 = cleaned_df[col].quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr
                cleaned_df[col] = cleaned_df[col].clip(lower=lower, upper=upper)

        # ── 15. Drop constant/empty columns ──────────────────────────────────
        if options.get("drop_constant_cols", False):
            constant_cols = [col for col in cleaned_df.columns if cleaned_df[col].nunique() <= 1]
            cleaned_df = cleaned_df.drop(columns=constant_cols)

        # ── 16. Drop high-cardinality columns (likely IDs) ────────────────────
        if options.get("drop_high_cardinality", False):
            threshold = float(options.get("cardinality_threshold", 95)) / 100.0
            high_card_cols = [
                col for col in cleaned_df.select_dtypes(include="object").columns
                if cleaned_df[col].nunique() / max(len(cleaned_df), 1) >= threshold
            ]
            cleaned_df = cleaned_df.drop(columns=high_card_cols)

        # ── 17. Standardise / Z-score normalize numeric columns ───────────────
        if options.get("standardize_numeric", False):
            for col in cleaned_df.select_dtypes(include=[np.number]).columns:
                mean = cleaned_df[col].mean()
                std = cleaned_df[col].std()
                if pd.notna(std) and std > 0:
                    cleaned_df[col] = (cleaned_df[col] - mean) / std

        # ── 18. Min-max normalize numeric columns ─────────────────────────────
        if options.get("minmax_normalize", False):
            for col in cleaned_df.select_dtypes(include=[np.number]).columns:
                col_min = cleaned_df[col].min()
                col_max = cleaned_df[col].max()
                if col_max != col_min:
                    cleaned_df[col] = (cleaned_df[col] - col_min) / (col_max - col_min)

        # ── 19. Detect and flag/remove email, URL, phone patterns ─────────────
        pii_action = options.get("pii_handling", "none")
        if pii_action != "none":
            email_re = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
            url_re = re.compile(r'https?://\S+|www\.\S+')
            phone_re = re.compile(r'\b[\+]?[\d]?[\s\-\.]?[\(]?[\d]{3}[\)]?[\s\-\.]?[\d]{3}[\s\-\.]?[\d]{4}\b')
            for col in cleaned_df.select_dtypes(include="object").columns:
                sample = cleaned_df[col].dropna().head(20).astype(str)
                is_pii = any(
                    email_re.search(v) or url_re.search(v) or phone_re.search(v)
                    for v in sample
                )
                if is_pii:
                    if pii_action == "redact":
                        cleaned_df[col] = cleaned_df[col].astype(str).apply(
                            lambda x: email_re.sub('[EMAIL]', url_re.sub('[URL]', phone_re.sub('[PHONE]', x)))
                        )
                    elif pii_action == "drop_col":
                        cleaned_df = cleaned_df.drop(columns=[col])

        # ── 20. Round numeric columns ─────────────────────────────────────────
        round_decimals = options.get("round_numeric", None)
        if round_decimals is not None:
            try:
                decimals = int(round_decimals)
                for col in cleaned_df.select_dtypes(include=[np.number]).columns:
                    cleaned_df[col] = cleaned_df[col].round(decimals)
            except (ValueError, TypeError):
                pass

        return cleaned_df


def _safe_float(val):
    try:
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return None
        return round(float(val), 4)
    except Exception:
        return None
