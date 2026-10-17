# Nexus

Discord moderation bot (anti-spam, link filter, URLhaus, warnings, verification).  
Runs in Docker, uses Turso as database, secrets via Doppler or `.env`.

## Quick start (VPS / Docker)

1. Put project files on the server.
2. Get `.env` from Doppler (Export → `.env`) or copy `.env.example` and fill it.
3. Required variables:
   - `DISCORD_TOKEN`
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
4. Optional:
   - `GUILD_ID` — faster slash sync while testing
   - `URLHAUS_AUTH_KEY` — malware URL detection

```bash
docker compose up -d --build
docker compose logs -f
```

## Discord setup

In Developer Portal enable:
- Message Content Intent
- Server Members Intent

Bot needs: Moderate Members, Kick, Ban, Manage Messages, Manage Channels, Manage Roles.

## Commands

- `/config ...` — settings
- `/warn`, `/warnings`, `/clear_warnings`
- `/timeout`, `/kick`, `/ban`, `/tempban`, `/unban`
- `/purge`, `/lock`, `/unlock`, `/slowmode`
- `/setup_verify`

See `DOPPLER.md` for secrets management.
