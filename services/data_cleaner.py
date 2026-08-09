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

        # 1. Strip and format column headers
        if options.get("header_formatting", False):
            new_columns = []
            for col in cleaned_df.columns:
                formatted = str(col).strip().lower()
                formatted = formatted.replace(" ", "_").replace(".", "_").replace("-", "_")
                while "__" in formatted:
                    formatted = formatted.replace("__", "_")
                new_columns.append(formatted)
            cleaned_df.columns = new_columns

        # 2. Parse numbers hidden in string format (e.g. "$1,250.50" -> 1250.5)
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

        # 3. Auto-parse date columns
        if options.get("parse_dates", False):
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    try:
                        test = pd.to_datetime(cleaned_df[col], infer_datetime_format=True, errors='coerce')
                        # Only convert if majority of values parsed successfully
                        if test.notna().sum() > len(cleaned_df) * 0.5:
                            cleaned_df[col] = test
                    except Exception:
                        pass

        # 4. Remove duplicate records
        if options.get("remove_duplicates", False):
            cleaned_df = cleaned_df.drop_duplicates()

        # 5. Handle Missing Values
        null_handling = options.get("null_handling", "none")
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
        elif null_handling == "forward_fill":
            cleaned_df = cleaned_df.fillna(method='ffill')
        elif null_handling == "backward_fill":
            cleaned_df = cleaned_df.fillna(method='bfill')

        # 6. Remove outliers via IQR method (numeric columns only)
        if options.get("remove_outliers_iqr", False):
            numeric_cols = cleaned_df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                q1 = cleaned_df[col].quantile(0.25)
                q3 = cleaned_df[col].quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr
                cleaned_df = cleaned_df[(cleaned_df[col].isna()) | ((cleaned_df[col] >= lower) & (cleaned_df[col] <= upper))]

        # 7. Drop constant/empty columns
        if options.get("drop_constant_cols", False):
            constant_cols = [col for col in cleaned_df.columns if cleaned_df[col].nunique() <= 1]
            cleaned_df = cleaned_df.drop(columns=constant_cols)

        # 8. Trim whitespace from string columns
        if options.get("trim_whitespace", False):
            for col in cleaned_df.columns:
                if cleaned_df[col].dtype == "object":
                    cleaned_df[col] = cleaned_df[col].str.strip()

        return cleaned_df


def _safe_float(val):
    try:
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return None
        return round(float(val), 4)
    except Exception:
        return None
