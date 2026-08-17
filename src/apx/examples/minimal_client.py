"""Minimal APX Client example."""
from apx.client import APXClient, LocalClientTransport
from apx.cloud import APX

def run_client():
    cloud = APX(plugins=False)
    
    # Use LocalClientTransport for in-memory testing (HTTPClientTransport for remote)
    # The client context declares what capabilities the client supports.
    client_context = {"capabilities": ["apx-base"]}
    client = APXClient(LocalClientTransport(cloud.session("human:test")), client_context)

    print("1. Discovery & Compatibility")
    manifest = client.discover()
    print(f"Discovered server: {manifest.identity.id} with {len(manifest.actions)} actions.")
    
    compat = client.check_compatibility()
    if not compat.compatible:
        print(f"Incompatible server: {compat.reasons}")
        return
    print("Server is compatible!")

    print("\n2. Invocation")
    # This will fail because 'example.hello' doesn't exist unless the minimal server is running
    # but it demonstrates structured failure handling:
    result = client.execute("example.hello")
    
    if result.ok:
        print(f"Success! Result: {result.result}")
    else:
        print(f"Failed. Error code: {result.error.code}")
        print(f"Error message: {result.error.message}")
        if result.error.code == "approval_required":
            print("Action requires confirmation!")

if __name__ == "__main__":
    run_client()
