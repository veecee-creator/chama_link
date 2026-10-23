# ChamaLink free demo deployment

This Render Blueprint creates a public demo using fictional sample members and
transactions. It does not import the local SQLite database, `.env` file, M-Pesa
credentials, or real member information. Do not add real records to this demo.

## What the free demo includes

- A Django web service and PostgreSQL database in Frankfurt.
- HTTPS, static assets, and a fictional Chama seeded at startup.
- A demo login configured as secret `DEMO_USERNAME` and `DEMO_PASSWORD`
  environment variables. Set both in Render when prompted; use a unique
  password of at least 14 characters.
- The configured demo login can exercise chairperson, treasurer, and secretary
  actions in the seeded fictional chama. Regular accounts keep their chama role
  permissions.
- The dashboard links directly to group finances and M-Pesa payments. In demo
  mode, the M-Pesa page is available to explore, but initiating real payments
  is disabled.
- The seeded sample chama is on ChamaLink Plus so the goal and meeting tools
  can be explored. Public group-plan requests are saved in Django Admin; set
  `CHAMALINK_SALES_EMAIL` and the SMTP settings in Render to receive lead
  notifications by email. Plus activation and billing are handled manually;
  this demo does not charge groups online.
- No persistent media disk. Uploaded files can disappear on redeploy/restart.
- Render free services may sleep when idle. Render's free PostgreSQL database
  expires after 30 days and has no backups, so this is for a temporary demo,
  not ongoing financial records.

## Deploy

1. Put this project in a private GitHub repository. The `.gitignore` excludes
   `.env`, SQLite databases, backups, and media; check before pushing that no
   secrets or real member records are tracked.
2. In Render, connect that repository and create a Blueprint from `render.yaml`.
3. Enter secret values for `DEMO_USERNAME` and `DEMO_PASSWORD` when Render asks.
   Keep them private. The demo password should not match any personal password.
4. Wait for the web service to finish deploying, then open its `onrender.com`
   URL on your phone and sign in with those demo credentials.

The free demo intentionally has no M-Pesa credentials or live payment flow.
For a production service with real financial records, use paid persistent
hosting, configure backups, email and Daraja credentials securely, and plan a
separate reviewed data migration. Render requires a Git provider repository
and account access to create the service; neither is connected from this
workspace yet.
