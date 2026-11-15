# Deploying the web demo

The browser demo uses Python's standard-library HTTP server, so it needs no web framework or
additional runtime dependency. It only uses fake price lists and does not save quotes, provide user
accounts, or protect confidential business data. Treat it as a learning showcase, not a production
quote service.

## Deploy on Render

1. Push the project to a GitHub repository.
2. In Render, create a **New Web Service** and connect the repository and branch.
3. Configure the service with:
   - Runtime: **Python**
   - Build command: `python -m pip install -r requirements.txt`
   - Start command: `python -m server`
4. Deploy the service and open the HTTPS URL Render provides.

The server binds to `0.0.0.0` and reads the listening port from the `PORT` environment variable
provided by the hosting platform. For local testing, `PORT` defaults to `8000`; open
`http://localhost:8000`.

See Render's [Web Services documentation](https://render.com/docs/web-services) for current
dashboard options and port-binding requirements.

Each click sends the browser's whole list of steps to `POST /api/replay`. The server replays
them on a fresh in-memory desk and returns the quotes (shaped for the chosen user) and the audit
log. Nothing is stored between requests, so visitors cannot see each other's quotes and a restart
loses nothing. Requests are limited to 64 KiB and 200 steps. Do not enter real customer, company,
or pricing information.
