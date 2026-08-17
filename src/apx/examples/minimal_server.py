"""Minimal APX Provider / Server example."""
from apx.providers import ActionProvider
from apx.cloud import APX

def start_server():
    provider = ActionProvider("example.provider")
    
    # 1. Read-style action
    @provider.action("example.hello", description="Say hello", risk="read")
    def hello():
        return {"message": "Hello from APX!"}
        
    # 2. Action with an input
    @provider.action("example.echo", description="Echo input",
                     input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                     risk="read")
    def echo(text: str):
        return {"echoed": text}
        
    # 3. Requirement example (requires specific permission and actor type)
    @provider.action("example.secure", description="Secure action",
                     permissions=("example.admin",),
                     actor_requirements=("human",),
                     risk="destructive",
                     confirmation="confirm")
    def secure():
        return {"status": "success", "secret_operation": True}

    # Validation
    errors = provider.validate()
    if errors:
        print("Provider validation failed:")
        for e in errors: print(f"- {e}")
        return

    # In a real app, you would expose `provider` over HTTP.
    # Here we register it locally for testing:
    cloud = APX(plugins=False)
    provider.register(cloud.actions)
    cloud.providers[provider.identity.id] = provider
    print("Provider successfully registered!")

if __name__ == "__main__":
    start_server()
