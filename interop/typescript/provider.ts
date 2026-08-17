// Minimal independent APX 0.1 Provider SDK/reference Provider. No Python imports.
import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { randomUUID } from "node:crypto";

type Json = Record<string, any>;
type Handler = (input: Json) => Json;
type Definition = { id: string; description: string; risk: string; confirmation: string; idempotent: boolean; input_schema: Json; output_schema: Json };

class APXProvider {
  id: string;
  name: string;
  actions = new Map<string, { definition: Definition; handler: Handler }>();
  prepared = new Map<string, Json>();
  results = new Map<string, Json>();
  receipts = new Map<string, Json>();
  keys = new Map<string, string>();
  constructor(id: string, name: string) { this.id=id; this.name=name; }
  action(definition: Definition, handler: Handler) { this.actions.set(definition.id, { definition, handler }); }
  manifest(): Json { return { apx_version: "0.1", manifest_version: "0.1", provider: { id: this.id, name: this.name, provenance: "native_provider" }, resources: [], actions: [...this.actions.values()].map(x => ({ apx: "0.1", type: "action.definition", read_only: x.definition.risk === "read", destructive: false, reversible: false, reverse_action: null, retry: x.definition.idempotent ? "idempotency_required" : "never", side_effects: [], required_permissions: [], provider: this.id, provenance: "native_provider", tags: [], version: "1.0", deprecated: false, credential_requirements: [], actor_requirements: [], preconditions: [], postconditions: [], constraints: {}, extensions: {}, ...x.definition })), authentication: [], confirmation_methods: ["confirm"], capabilities: ["discover","prepare","authorize","execute","status","receipts","cancel"], transports: [{ type: "http", version: "0.1", protocol_endpoint: "/apx/v0.1" }], compatibility: ["0.1"], profiles: [], metadata: {} }; }
  prepare(request: Json): Json { const item=this.actions.get(request.action); if (!item) return failure(request,"rejected","unsupported_action"); const id="pa_"+randomUUID(); const value={ apx:"0.1",type:"action.prepared",action:request.action,target:request.target,input:request.input,effect:item.definition.description,confirmation_required:item.definition.confirmation,reversible:false,reverse_action:null,expires_at:new Date(Date.now()+120000).toISOString(),request_id:request.request_id,provider:this.id,side_effects:[],provider_conditions:[],confirmation_terms:null,prepared_action_id:id,created_at:new Date().toISOString(),authoritative_state_version:"1",authoritative_state:{ renewal },preconditions:[],resolved_terms:{},status:"prepared" }; this.prepared.set(id,value); return value; }
  authorize(id: string, confirmation: Json): Json { const p=this.prepared.get(id); if (!p || confirmation.prepared_action_id!==id || confirmation.confirmed!==true || confirmation.level!==p.confirmation_required) return failure({action:p?.action||"unknown",request_id:p?.request_id,target:p?.target||{}},"authorization_required","confirmation_required"); p.status="authorized"; return success(p,"authorized",{prepared_action_id:id}); }
  execute(request: Json): Json { if (request.idempotency_key && this.keys.has(request.idempotency_key)) return this.results.get(this.keys.get(request.idempotency_key)!)!; const item=this.actions.get(request.action),p=this.prepared.get(request.prepared_action_id); if (!item || !p || p.status!=="authorized" || JSON.stringify(p.input)!==JSON.stringify(request.input)) return failure(request,"rejected","precondition_failed"); const result=item.handler(request.input); const receipt={apx:"0.1",type:"action.receipt",receipt_id:randomUUID(),request_id:request.request_id,prepared_action_id:p.prepared_action_id,action:request.action,provider:this.id,target:request.target,actor:request.actor,status:"completed",result,verification_status:"verified",reversible:false,side_effects:[],postconditions:[],partial_effects:[],timestamp:new Date().toISOString()}; const value={apx:"0.1",type:"action.result",action:request.action,request_id:request.request_id,target:request.target,ok:true,status:"completed",result,error:null,receipt,data:result,host:null}; this.results.set(request.request_id,value); this.receipts.set(receipt.receipt_id,receipt); if(request.idempotency_key)this.keys.set(request.idempotency_key,request.request_id); return value; }
  cancel(id:string):Json { const p=this.prepared.get(id); if(!p||["accepted","executing","completed"].includes(p.status))return failure({action:p?.action||"unknown",request_id:p?.request_id,target:p?.target},"rejected","state_conflict");p.status="cancelled";return success(p,"cancelled",{committed:false}); }
}
function failure(r:Json,status:string,code:string):Json{return {apx:"0.1",type:"action.result",action:r.action,request_id:r.request_id,target:r.target||{},ok:false,status,result:null,error:{code,message:code,details:{},retryable:false,provider_code:null,retry_after:null,next_actions:[]},receipt:null,data:null,host:null};}
function success(p:Json,status:string,result:Json):Json{return {apx:"0.1",type:"action.result",action:p.action,request_id:p.request_id,target:p.target,ok:true,status,result,error:null,receipt:null,data:result,host:null};}
let renewal=true;
const provider=new APXProvider("typescript.local","TypeScript Reference");
provider.action({id:"subscription.cancel",description:"Disable renewal",risk:"account_change",confirmation:"confirm",idempotent:true,input_schema:{type:"object",properties:{},additionalProperties:false},output_schema:{type:"object"}},()=>({renewal:renewal=false}));
const server=createServer(async(req:IncomingMessage,res:ServerResponse)=>{let raw="";for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):{};let value:Json;
 if(req.method==="GET"&&req.url==="/.well-known/apx")value=provider.manifest();
 else if(req.method==="POST"&&req.url==="/apx/v0.1/prepare")value=provider.prepare(body);
 else if(req.method==="POST"&&req.url==="/apx/v0.1/authorize")value=provider.authorize(body.prepared_action_id,body.confirmation);
 else if(req.method==="POST"&&req.url==="/apx/v0.1/execute")value=provider.execute(body);
 else if(req.method==="GET"&&req.url?.startsWith("/apx/v0.1/status/"))value=provider.results.get(req.url.split("/").pop()!)||{error:{code:"invalid_request"}};
 else if(req.method==="GET"&&req.url?.startsWith("/apx/v0.1/receipts/"))value=provider.receipts.get(req.url.split("/").pop()!)||{error:{code:"invalid_request"}};
 else if(req.method==="POST"&&req.url==="/apx/v0.1/cancel")value=provider.cancel(body.prepared_action_id);
 else value={error:{code:"invalid_request"}};
 const encoded=JSON.stringify(value);res.writeHead(200,{"Content-Type":"application/apx+json","Content-Length":Buffer.byteLength(encoded)});res.end(encoded);
});
server.listen(0,"127.0.0.1",()=>console.log(JSON.stringify({port:(server.address() as any).port})));
