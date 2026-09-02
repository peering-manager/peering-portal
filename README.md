# Peering Portal

A companion web app for the [Peering Manager](https://peering-manager.net)
Portal API. External networks get a form-based wizard to submit BGP peering
requests and to track them afterwards. For the API spec, the glossary and the
request lifecycle, see the
[portal integration docs](https://docs.peering-manager.net/integrations/peering-portal/).

```
                                     <--Token auth-->  Peering Manager
Browser  <--HTML-->  FastAPI portal                    /api/peering/portal/
                       (server.py)
                                     <---OAuth 2.0-->  PeeringDB
```

One API token authenticates the portal to Peering Manager. PeeringDB tells the
portal which networks a visitor may act for, see [ASN ownership](#asn-ownership).

The portal has its own version numbers, so it needs a matching server:

| Portal | Peering Manager |
| --- | --- |
| 0.x | 1.11 or later |

## Quick start

You need Python 3.12+, a Peering Manager 1.11+ instance, and an API token from a
user who holds the *Add* and *Change* peering-request permissions and has an
affiliated AS selected, as the
[integration docs](https://docs.peering-manager.net/integrations/peering-portal/#authentication-and-permissions)
describe.

```sh
cp .env.example .env    # or: cp config.example.toml config.toml
# PM_URL and PM_TOKEN are required. Add PDB_CLIENT_ID and PDB_CLIENT_SECRET
# before you let anybody else in, see ASN ownership.

uv sync
uv run python server.py     # http://localhost:8080
```

### Docker

```sh
docker compose up -d
```

The container publishes `127.0.0.1:8080`, for a reverse proxy on the same host.
Set `BIND=0.0.0.0` to serve it directly.

To let Traefik terminate TLS and renew the certificate, set `PORTAL_HOST` and
`ACME_EMAIL` in `.env`, point that name at this host, open ports 80 and 443,
then:

```sh
docker compose -f docker-compose.yaml -f docker-compose.traefik.yaml up -d
```

Traefik reads its routes from the container labels, so it mounts the docker
socket. The mount is read-only, but socket access still amounts to root on the
host.

## Configuration

Settings come from the environment, from a `.env` file in the working directory,
or from a TOML file (`config.toml`, or the path in `PORTAL_CONFIG`). The
environment wins. See `.env.example` and `config.example.toml`.

| Variable | TOML key | Description |
| --- | --- | --- |
| `PM_URL` | `pm_url` | **Required.** Peering Manager base URL. |
| `PM_TOKEN` | `pm_token` | **Required.** Peering Manager API token, server-side only. |
| `SECRET_KEY` | `secret_key` | Signs the session cookie. Random at startup when unset, which signs every visitor out on each restart. |
| `SESSION_COOKIE_SECURE` | `session_cookie_secure` | Mark the session cookie `Secure`. Set it on any HTTPS deployment. |
| `PDB_CLIENT_ID` | `pdb_client_id` | PeeringDB OAuth client ID. Together with the secret it turns the ASN check on. |
| `PDB_CLIENT_SECRET` | `pdb_client_secret` | PeeringDB OAuth client secret. |
| `PDB_REDIRECT_URI` | `pdb_redirect_uri` | Public URL of `/auth/callback`. It must match what PeeringDB holds, character for character. Built from the request when unset, which is wrong behind a proxy. |
| `PDB_REQUIRED_PERMS` | `pdb_required_perms` | Rights a network must grant the user. Default `0`, any affiliation. |
| `PDB_AUTHORIZE_URL`, `PDB_TOKEN_URL`, `PDB_USERINFO_URL` | the same, lowercased | The PeeringDB endpoints. Set them only if PeeringDB moves them. |
| `HOST`, `PORT` | `host`, `port` | Bind address and port. Default `0.0.0.0:8080`. |
| `RELOAD` | `reload` | uvicorn auto-reload, development only. |

One instance serves one affiliated AS. To host several, deploy one portal per
AS, each with its own user and token.

## ASN ownership

Peering Manager authenticates the portal as a whole and does **not** check that
the ASN in a request belongs to the visitor. The portal does that, with
[PeeringDB OAuth](https://docs.peeringdb.com/oauth/): the visitor signs in,
PeeringDB reports their network affiliations, and the portal accepts requests
for those networks only.

> [!WARNING]
> The check is off until you set `PDB_CLIENT_ID` and `PDB_CLIENT_SECRET`, and
> until then anybody can claim any ASN. The portal says so at startup and on the
> welcome page. Configure it before you go to production.

### Setting it up

1. Open <https://www.peeringdb.com/oauth2/applications/> and register an
   application. Client type **Confidential**, grant type **Authorization
   code**, redirect URI the `/auth/callback` route of your portal.
2. Copy the client ID and the secret from the page shown right after you save,
   see the trap below.
3. Set `PDB_CLIENT_ID`, `PDB_CLIENT_SECRET`, `PDB_REDIRECT_URI` and
   `SESSION_COOKIE_SECURE`, then restart the portal.

Once it is on, the welcome page asks for a sign-in first, the ASN field becomes
a list of the affiliated networks, every wizard step and every submission checks
the ASN against that list again, and a tracking ID only opens or cancels a
request for the network that filed it.

`PDB_REQUIRED_PERMS` asks for more than a bare affiliation. PeeringDB grants `1`
read, `2` update, `4` create and `8` delete, added together. Use `2` to keep out
the members who can only read the network, or `15` to accept the administrators
of the organisation only.

### The client secret trap

> [!WARNING]
> PeeringDB stores the secret hashed, and its form shows you that **hash**
> afterwards, not the secret. A hash starts with `argon2$` or `pbkdf2_sha256$`,
> and sending one gives `401 invalid_client` on every sign-in.

Type a secret you know into the field and save it, for instance the output of
`openssl rand -hex 64`. PeeringDB hashes what you type and leaves an existing
hash alone. Keep to letters and digits, because docker compose expands `$` in a
`.env` file.

To check the credentials without a browser, ask for a token with a made-up
code. `400 invalid_grant` means they pass, `401 invalid_client` means they do
not:

```sh
set -a && . ./.env && set +a
curl -s -w '\n%{http_code}\n' -d grant_type=authorization_code -d code=not-a-real-code \
  -d "redirect_uri=$PDB_REDIRECT_URI" -d "client_id=$PDB_CLIENT_ID" \
  -d "client_secret=$PDB_CLIENT_SECRET" https://auth.peeringdb.com/oauth2/token/
```

Send them as request parameters, as `oauth.py` does: PeeringDB reads an
`Authorization: Basic` header as a user login. When that call passes but the
portal still gets a 401, the container holds the old value, so run
`docker compose up -d --force-recreate portal`.

### How it works

`oauth.py` implements the authorization code flow with PKCE, so there is no
OAuth library to keep up to date. `/login` puts a one-shot state and verifier in
the session, and `/auth/callback` matches the state, trades the code for an
access token and reads the profile. The `networks` scope is the one that
matters: it carries the affiliations that become the allowlist. The identity and
the ASN list live in the session cookie, the access token is used once and
dropped, and nothing is stored server-side. `POST /logout` clears the session,
which otherwise expires after 30 minutes without a request. Every guarded page
refreshes that window, and a sign-in lasts 12 hours at the outside, so an
affiliation withdrawn on PeeringDB stops working here within the day.

## License

Apache 2.0
