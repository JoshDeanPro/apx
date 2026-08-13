from .models import DatabaseResource

def from_db_instance(instance: dict, *, groups=(), tags=()) -> DatabaseResource:
    endpoint=instance.get("Endpoint") or {}; engine=instance.get("Engine","unknown")
    return DatabaseResource(instance.get("DBInstanceIdentifier",endpoint.get("Address","aws-database")),engine,endpoint.get("Address",""),int(endpoint.get("Port",0)),instance.get("DBName"),instance.get("MasterUsername"),None,"require" if instance.get("StorageEncrypted") else None,"aws",instance.get("EngineVersion"),None,tuple(groups),tuple(tags),{"arn":instance.get("DBInstanceArn"),"status":instance.get("DBInstanceStatus")})
