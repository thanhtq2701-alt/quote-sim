# Deploying the web demo

The browser demo uses Python's standard-library HTTP server, so it needs no web framework or
additional runtime dependency. It only uses fake price lists and does not save quotes, provide user
accounts, or protect confidential business data. Treat it as a learning showcase, not a production
quote service.

## Deploy on Render

The service is described in [`render.yaml`](../render.yaml) (a Render *Blueprint*), so every
setting is in the repository and changes to it go through a pull request:

| Setting | Value | Why |
|---|---|---|
| Plan | `free` | A fake-data demo; see the free-plan limits below. |
| Branch | `main` | Only reviewed, merged code is deployed. |
| Build command | `python -m tools.check_data` | Nothing to install (standard library only); a broken data file fails the build and the previous deploy keeps running. |
| Start command | `python -m server` | Same command as local use. |
| Health check | `GET /api/catalog` | Loads the fake data on every request, so a 200 means server and data both work. |
| Auto-deploy | `checksPass` | A push to `main` is deployed only after the CI checks pass. |
| `PYTHON_VERSION` | `3.14.10` | A version CI tests and the development machine uses. |

First deploy (done once, by the repository owner):

1. Sign in to the Render Dashboard and connect your GitHub account.
2. Click **New > Blueprint**, choose this repository, and give the Blueprint a name.
3. Check that Render shows one web service called `quote-sim`, then click **Deploy Blueprint**.
4. Wait for the deploy to finish and open the `https://...onrender.com` URL Render shows.

Manage the service only through this Blueprint. Do not also create the same service by hand in the
dashboard: Render's documentation warns against managing one resource from more than one place.

After that, merging a pull request into `main` deploys automatically once CI is green. Changing a
setting means editing `render.yaml` in a pull request, not clicking in the dashboard.

## Check a deploy

Replace the URL with the one Render shows:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://YOUR-SERVICE.onrender.com/
curl -s https://YOUR-SERVICE.onrender.com/api/catalog
```

Expected: `200` for the page, and JSON with users, price lists, and policy values but no costs.
Then open the URL in a browser and click through one quote; denied actions should appear in the
audit log.

## Free plan limits

According to Render's [free instance documentation](https://render.com/docs/free):

- The service sleeps after 15 minutes without traffic. The next visit wakes it in about a minute,
  and the browser shows a loading page meanwhile.
- Render may restart a free service at any time, and the local filesystem is not kept.
- A workspace gets 750 free instance hours per month; sleeping services do not use hours.

None of this breaks the demo, because the server stores nothing between requests (see below).

## Upgrading Python

1. Add the new version to the matrix in `.github/workflows/tests.yml` and get CI green.
2. Change `PYTHON_VERSION` in `render.yaml` to the full version (for example `3.15.2`).

Doing it in this order means the deployed version is always one that CI has tested.

## How the server works

The server binds to `0.0.0.0` and reads the listening port from the `PORT` environment variable
provided by the hosting platform (Render sets `10000`). For local testing, `PORT` defaults to
`8000`; open `http://localhost:8000`.

Each click sends the browser's whole list of steps to `POST /api/replay`. The server replays
them on a fresh in-memory desk and returns the quotes (shaped for the chosen user) and the audit
log. Nothing is stored between requests, so visitors cannot see each other's quotes and a restart
loses nothing. Requests are limited to 64 KiB and 200 steps. Do not enter real customer, company,
or pricing information.
