# Security policy

## Supported versions

Raven Ledger is a self-hosted application maintained as a rolling release.
Only the newest published release receives security fixes. Operators should
keep a database backup, retain the existing Fernet key, and upgrade promptly
after a security release is announced.

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, household data,
or a vulnerable public URL. Use GitHub private vulnerability reporting
(Security → Report a vulnerability) and include:

- the affected version or image digest;
- the smallest reproducible request or code path;
- the expected and observed authorization boundary;
- impact and any evidence of exploitation; and
- whether a secret, Plaid token, or household record may be exposed.

Never include a live password, session cookie, API key, Plaid secret,
Cloudflare token, or Fernet key. Use synthetic values in reproductions.

The maintainer will acknowledge a report as soon as practical, validate its
scope privately, rotate affected credentials immediately, and publish a fixed
version after regression tests and container scans pass. Public disclosure
should wait until operators have a reasonable opportunity to update.

## Operator incident checklist

1. Disable or revoke the affected Raven session/API key or upstream token.
2. Preserve application, Cloudflare, PostgreSQL, and TrueNAS logs without
   copying secrets into tickets or chat.
3. Take a database backup and a TrueNAS snapshot before changing containers.
4. Patch and redeploy by immutable version/digest when available.
5. Rotate `SECRET_KEY`, database/Redis passwords, Plaid credentials, or tunnel
   tokens according to the affected boundary. Do not replace
   `ENCRYPTION_KEY` without first re-encrypting stored provider tokens.
6. Review household sessions, bank connections, exports, and backup access for
   unexpected activity.
