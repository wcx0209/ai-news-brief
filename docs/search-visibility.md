# Daily lead search visibility

The [monitor workflow](../.github/workflows/search-visibility.yml) runs on GitHub every three hours at minute 37 UTC. A manual dispatch on `main` runs the same checks. It follows the lead article on each dated AI edition and each field's lead, counts each English and Chinese article URL separately, and stores observations in the project's Supabase PostgreSQL database.

## Read the report

Open the SQL editor in the project's Supabase dashboard and run this query as the database owner. The breakdown covers headlines published in the past 35 days.

```sql
select generated_at, report->>'mode' as mode,
       jsonb_pretty(report->'rates_by_locale') as indexing_rates
from search_monitor_private.latest_report
where id = 1;
```

Open the `urls` array of the same report to see individual articles. The 24-, 48- and 72-hour checkpoints use time since publication on PolyEmergence, with a six-hour observation window. A missed check has unknown status and is excluded from the rate. Each observed checkpoint includes its actual collection time. The earliest reported impression has an hourly estimate in UTC when available, a finalized calendar date in Pacific time when available, and a timestamp for when the API first returned it. An empty result can change as Google finishes processing the data.

## Cloud access

The workflow uses the existing `INBRIEF_SUPABASE_DB_URL` GitHub Actions secret. Configure the following repository **variables** for Google Workload Identity Federation.

| Variable | Value |
| --- | --- |
| `GSC_WIF_PROVIDER` | Full workload identity provider resource name, beginning with `projects/<project-number>/locations/global/workloadIdentityPools/` |
| `GSC_SERVICE_ACCOUNT` | Google service account email with access to the `https://polyemergence.com/` Search Console property |

Enable the Search Console API for that project. Restrict the provider to this repository's numeric ID, `refs/heads/main`, and this workflow's path. Grant that identity `roles/iam.workloadIdentityUser` on the service account. The monitor requests `webmasters.readonly`; GitHub obtains short-lived credentials for each run.

While the two variables are being configured, the workflow can register newly published headlines. The Actions job summary indicates when only discovery ran. Individual page results and search metrics stay in the private database.
