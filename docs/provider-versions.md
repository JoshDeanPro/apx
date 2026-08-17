# Provider version sources

APX records provider version knowledge as metadata and does not upgrade
or migrate integrations automatically. These are the official references used
for the 0.4 integration catalog (reviewed 2026-08-13):

- Porkbun API v3 / v3.9 documentation: <https://porkbun.com/api/json/v3/documentation/interactive>
- Cloudflare client v4 API: <https://developers.cloudflare.com/api/>
- GoDaddy Domains v1/v2/v3 overview: <https://developer.godaddy.com/en/docs/api-users/how-godaddy-apis-work>
- Discord REST API v10 resources: <https://docs.discord.com/developers/reference>
- OpenAI REST v1 API reference: <https://developers.openai.com/api/reference/overview>
- Airtable Web API v0: <https://airtable.com/developers/web/api/introduction>
- DigitalOcean API v2: <https://docs.digitalocean.com/reference/api/api-reference/>
- Supabase Management API v1: <https://supabase.com/docs/reference/api/introduction>
- AWS RDS DBInstance representation: <https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_DBInstance.html>
- Tailscale CLI status JSON: <https://tailscale.com/kb/1552/tailscale-services>

`latest_known` is populated only when an official reference supplies a useful
release designation. Runtime response headers such as `X-API-Version` and
`openai-version` are returned as detected API metadata when providers supply
them.
