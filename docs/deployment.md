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
   - Start command: `python -m quote_sim.web`
4. Deploy the service and open the HTTPS URL Render provides.

The server binds to `0.0.0.0` and reads the listening port from the `PORT` environment variable
provided by the hosting platform. For local testing, `PORT` defaults to `8000`; open
`http://localhost:8000`.

See Render's [Web Services documentation](https://render.com/docs/web-services) for current
dashboard options and port-binding requirements.

The form runs one in-memory scenario per request. It accepts a fake product quantity, discount, and
price-list version, then displays calculated totals and the audit entries for that run. Refreshing
or submitting another request does not preserve previous quote state. Do not enter real customer,
company, or pricing information.
