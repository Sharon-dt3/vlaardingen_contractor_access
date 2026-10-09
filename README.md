# Renewi contractor and visitor site access

Digital site access and compliance for contractors, drivers and visitors entering a Renewi site. This repository holds two versions of the same demo.

| Folder | What it is |
|---|---|
| `Contractor-Visitor-Site-Access-feature-manager-access-workflow/` | **v1.** The DigitalT3 demo application, kept exactly as received. |
| `v2/` | **v2.** A copy of v1 with one requirement added: a contractor confirms that they have read and understood the life-saving rules before entering site, and the site can see that they did. See [v2/V2_CHANGES.md](v2/V2_CHANGES.md). |

Both are a FastAPI API with PostgreSQL and a Next.js web app. All people, companies and documents in them are synthetic, and the identity, document-reading and notification providers are simulated and labelled `DEMO MODE`.

## Run v2

```bash
cd v2
scripts/run-without-docker.sh start    # first run installs everything, then starts it
```

Then open http://localhost:3000 and sign in as `admin.demo`. The demo password is already filled in on the sign-in page. Stop it with `scripts/run-without-docker.sh stop`.

It needs Python 3.12, Node.js 20 or later and PostgreSQL 17. If you prefer Docker, `docker compose --profile application up --build` from inside `v2/` or the v1 folder starts the same stack.

## Status

- The life-saving rules wording in v2 is **sample text**. Renewi's own rules and approved legal wording must replace it before any real use.
- The walk-up flow (scan a QR code, register with name and company, read and acknowledge the rules, with no prior invitation) is not built yet.
