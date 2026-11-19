"""Google Trends public dataset in BigQuery: the top and rising search terms of every Indian state, one query a day.

`bigquery-public-data.google_trends.international_top_terms` and `international_top_rising_terms` are partitioned by
`refresh_date` and not clustered, so a query is billed for the columns it reads in the partitions it names, however few
rows it keeps: about 0.9 GB for both tables, one partition, all 36 states. Hence one query for all states, a partition
filter on every query, a dry run before every real run (free; it also finds the newest partition, because a missing one
estimates 0 bytes) and a hard `maximum_bytes_billed`. Queries are parameterised; nothing is concatenated into SQL.

Everything here is blocking (the BigQuery client is); callers run `fetch_india` in a thread. Tests pass a fake client.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)

DATASET = "bigquery-public-data.google_trends"
COUNTRY = "IN"
LOOKBACK_DAYS = 5  # the newest partition is at most this many days old; older than that is a stale dataset, not a gap

# The dataset's regions for India (verified 2026-11-19): ISO 3166-2:IN code -> region_name. Omnicult uses the current
# codes, the dataset the older ones for three states, keeps Daman and Diu and Dadra and Nagar Haveli apart (Omnicult
# `IN-DH` is both) and has no Ladakh (`IN-LA`).
DATASET_REGIONS = {
    "IN-AN": "Andaman and Nicobar Islands", "IN-AP": "Andhra Pradesh", "IN-AR": "Arunachal Pradesh", "IN-AS": "Assam",
    "IN-BR": "Bihar", "IN-CH": "Chandigarh", "IN-CT": "Chhattisgarh", "IN-DD": "Daman and Diu", "IN-DL": "Delhi",
    "IN-DN": "Dadra and Nagar Haveli", "IN-GA": "Goa", "IN-GJ": "Gujarat", "IN-HP": "Himachal Pradesh", "IN-HR": "Haryana",
    "IN-JH": "Jharkhand", "IN-JK": "Jammu and Kashmir", "IN-KA": "Karnataka", "IN-KL": "Kerala", "IN-LD": "Lakshadweep",
    "IN-MH": "Maharashtra", "IN-ML": "Meghalaya", "IN-MN": "Manipur", "IN-MP": "Madhya Pradesh", "IN-MZ": "Mizoram",
    "IN-NL": "Nagaland", "IN-OR": "Odisha", "IN-PB": "Punjab", "IN-PY": "Puducherry", "IN-RJ": "Rajasthan",
    "IN-SK": "Sikkim", "IN-TG": "Telangana", "IN-TN": "Tamil Nadu", "IN-TR": "Tripura", "IN-UP": "Uttar Pradesh",
    "IN-UT": "Uttarakhand", "IN-WB": "West Bengal",
}
_RENAMED = {"IN-CG": "IN-CT", "IN-OD": "IN-OR", "IN-TS": "IN-TG"}  # Omnicult code -> dataset code, where they differ
_OMNICULT = {dataset: omnicult for omnicult, dataset in _RENAMED.items()}


def dataset_region(code: str) -> str | None:
    """The dataset's region_code for an Omnicult state code, or None where the dataset has no such region."""
    dataset = _RENAMED.get(code, code)
    return dataset if dataset in DATASET_REGIONS and dataset not in ("IN-DD", "IN-DN") else None


def omnicult_region(dataset_code: str) -> str | None:
    """The Omnicult state code for a dataset region_code (None for Daman and Diu and Dadra and Nagar Haveli)."""
    if dataset_code in ("IN-DD", "IN-DN") or dataset_code not in DATASET_REGIONS:
        return None
    return _OMNICULT.get(dataset_code, dataset_code)


# --- typed failures ---------------------------------------------------------------------------------------------------


class TrendsError(Exception):
    reason = "failed"


class TrendsNotConfigured(TrendsError):
    reason = "not_configured"


class TrendsPermission(TrendsError):
    reason = "permission"


class TrendsQuota(TrendsError):
    reason = "quota"


_QUOTA_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded", "bytesBilledLimitExceeded", "resourcesExceeded"}


def classify(error: Exception) -> TrendsError:
    """Map a BigQuery or auth failure to one of the typed errors; anything else is a plain TrendsError."""
    from google.api_core import exceptions as gax
    from google.auth import exceptions as auth

    if isinstance(error, TrendsError):
        return error
    if isinstance(error, auth.DefaultCredentialsError | auth.RefreshError):
        return TrendsNotConfigured("Google credentials are not available to the API.")
    reasons = {str(e.get("reason", "")) for e in (getattr(error, "errors", None) or []) if isinstance(e, dict)}
    text = str(error).lower()
    if isinstance(error, gax.TooManyRequests) or reasons & _QUOTA_REASONS or "bytes billed" in text or "quota" in text:
        return TrendsQuota("BigQuery refused the query: a quota or the bytes-billed cap was reached.")
    if isinstance(error, gax.Unauthorized | gax.Forbidden | gax.PermissionDenied):
        return TrendsPermission("The API's service account may not run BigQuery jobs (it needs roles/bigquery.jobUser).")
    return TrendsError(f"BigQuery failed ({type(error).__name__}).")


# --- the query --------------------------------------------------------------------------------------------------------

_COLUMNS = "week, region_code, term, rank, score"
_FILTER = "refresh_date = @refresh_date AND country_code = @country AND region_code IN UNNEST(@regions) AND week >= @since"
SQL = f"""
SELECT 'top' AS kind, {_COLUMNS}, CAST(NULL AS INT64) AS percent_gain
FROM `{DATASET}.international_top_terms` WHERE {_FILTER}
UNION ALL
SELECT 'rising' AS kind, {_COLUMNS}, percent_gain
FROM `{DATASET}.international_top_rising_terms` WHERE {_FILTER}
"""


@dataclass(frozen=True)
class Fetched:
    refresh_date: date
    rows: list[dict[str, Any]]  # kind, week, region_code (the dataset's), term, rank, score, percent_gain
    job_id: str | None
    bytes_processed: int | None
    bytes_billed: int | None


def make_client(settings: Settings) -> Any:
    from google.cloud import bigquery

    from app.llm.google import load_credentials

    project = settings.bigquery_project or settings.google_cloud_project
    if not project:
        raise TrendsNotConfigured("BIGQUERY_PROJECT (or GOOGLE_CLOUD_PROJECT) is not set.")
    try:
        return bigquery.Client(project=project, credentials=load_credentials())
    except Exception as error:
        raise classify(error) from error


def fetch_india(settings: Settings, *, client: Any | None = None, today: date | None = None, skip_refresh_date: date | None = None) -> Fetched | None:
    """Run the one query: the newest `refresh_date` partition, India, every state, the latest `search_pulse_weeks` weeks.

    Returns None, without running the query, when the newest partition is `skip_refresh_date` (already stored). Raises a
    TrendsError subclass for every failure."""
    from google.cloud import bigquery

    try:
        client = client or make_client(settings)
        cap = settings.search_pulse_max_bytes

        def config(d: date, **extra: Any) -> Any:
            return bigquery.QueryJobConfig(
                maximum_bytes_billed=cap, use_query_cache=True, query_parameters=[
                    bigquery.ScalarQueryParameter("refresh_date", "DATE", d),
                    bigquery.ScalarQueryParameter("country", "STRING", COUNTRY),
                    bigquery.ArrayQueryParameter("regions", "STRING", sorted(DATASET_REGIONS)),
                    bigquery.ScalarQueryParameter("since", "DATE", d - timedelta(days=7 * settings.search_pulse_weeks)),  # weeks start on Sundays
                ], **extra)

        day = today or date.today()
        for back in range(LOOKBACK_DAYS):
            candidate = day - timedelta(days=back)
            estimate = client.query(SQL, job_config=config(candidate, dry_run=True)).total_bytes_processed or 0
            if estimate:
                break  # a partition that does not exist estimates 0 bytes
        else:
            raise TrendsError(f"The dataset has no refresh_date partition in the last {LOOKBACK_DAYS} days.")
        logger.info("search pulse dry run: refresh_date=%s estimated_bytes=%d cap=%d", candidate, estimate, cap)
        if candidate == skip_refresh_date:
            return None
        if estimate > cap:
            raise TrendsQuota(f"The query would read {estimate} bytes, over the cap of {cap}.")
        job = client.query(SQL, job_config=config(candidate))
        rows = [dict(row) for row in job.result(timeout=settings.search_pulse_timeout_seconds)]
        logger.info("search pulse query: job=%s rows=%d bytes_processed=%s bytes_billed=%s", job.job_id, len(rows),
                    job.total_bytes_processed, job.total_bytes_billed)
        return Fetched(candidate, rows, job.job_id, job.total_bytes_processed, job.total_bytes_billed)
    except TrendsError:
        raise
    except Exception as error:
        raise classify(error) from error
