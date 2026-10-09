# Renewi contractor and visitor site access (v2)

Digital site access and compliance for contractors, drivers and visitors entering a Renewi site.

The application is in [`v2/`](v2/). It is a copy of the DigitalT3 demo application (v1, not included here) with one requirement added: a contractor confirms that they have read and understood the life-saving rules before entering site, and the site can see that they did. See [v2/V2_CHANGES.md](v2/V2_CHANGES.md) for what changed and why.

It is a FastAPI API with PostgreSQL and a Next.js web app. All people, companies and documents are synthetic, and the identity, document-reading and notification providers are simulated and labelled `DEMO MODE`.

## Run it

```bash
cd v2
scripts/run-without-docker.sh start    # first run installs everything, then starts it
```

Then open http://localhost:3000 and sign in as `admin.demo`. The demo password is already filled in on the sign-in page. Stop it with `scripts/run-without-docker.sh stop`.

It needs Python 3.12, Node.js 20 or later and PostgreSQL 17. If you prefer Docker, `docker compose --profile application up --build` from inside `v2/` starts the same stack.

## Status

- The life-saving rules wording is **sample text**. Renewi's own rules and approved legal wording must replace it before any real use.
- The walk-up flow (scan a QR code, register with name and company, read and acknowledge the rules, with no prior invitation) is not built yet.
