// Independent APX 0.1 reference client. It imports no APX/Python internals.
type Json = Record<string, unknown>;

const origin = process.argv[2];
if (!origin) throw new Error("usage: node client.ts PROVIDER_ORIGIN");

async function call(path: string, body?: Json): Promise<Json> {
  const response = await fetch(origin + path, {
    method: body ? "POST" : "GET",
    headers: { Accept: "application/apx+json", "Content-Type": "application/apx+json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return await response.json() as Json;
}

const manifest = await call("/.well-known/apx");
if (manifest.apx_version !== "0.1") throw new Error("unsupported protocol");
const requestId = crypto.randomUUID();
const request: Json = {
  apx: "0.1", type: "action.request", protocol_version: "0.1",
  action: "subscription.cancel", target: {}, input: {}, request_id: requestId,
  created_at: new Date().toISOString(), actor: "agent:typescript",
  auth_context: { principal_id: "agent:typescript", authentication_method: "test" },
};
const prepared = await call("/apx/v0.1/prepare", request);
if (prepared.type !== "action.prepared") throw new Error(JSON.stringify(prepared));
const preparedId = prepared.prepared_action_id as string;
const authorization = await call("/apx/v0.1/authorize", {
  prepared_action_id: preparedId,
  confirmation: { prepared_action_id: preparedId, level: "confirm", confirmed: true,
    authorization_id: crypto.randomUUID(), expires_at: new Date(Date.now() + 60000).toISOString() },
});
if (authorization.status !== "authorized") throw new Error(JSON.stringify(authorization));
const executed = await call("/apx/v0.1/execute", {
  ...request, prepared_action_id: preparedId, idempotency_key: "typescript-cancel-1",
  authoritative_state_version: prepared.authoritative_state_version,
});
if (executed.status !== "completed") throw new Error(JSON.stringify(executed));
const recovered = await call("/apx/v0.1/status/" + requestId);
if ((recovered.receipt as Json).receipt_id !== (executed.receipt as Json).receipt_id)
  throw new Error("ambiguous execution recovery failed");
console.log(JSON.stringify({ provider: (manifest.provider as Json).id, status: executed.status,
  renewal: (executed.result as Json).renewal, receipt_id: (executed.receipt as Json).receipt_id }));
