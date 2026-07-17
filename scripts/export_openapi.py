"""Write the FastAPI OpenAPI schema to web/openapi.json (deterministic)."""
import json
import pathlib

from storygen_api.main import app

out = pathlib.Path(__file__).resolve().parent.parent / "web" / "openapi.json"
schema = app.openapi()
out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
print(f"wrote {out}")
