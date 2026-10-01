import uvicorn
import os
from services.db_service import init_db

if __name__ == "__main__":
    print("=" * 60)
    print("ShipFlow Quoting SaaS Platform")
    print("=" * 60)
    print("Initializing Database...")
    init_db()
    print("Starting Web Server at http://127.0.0.1:8000")
    print("Swagger API Docs available at http://127.0.0.1:8000/docs")
    print("Showcase available at http://127.0.0.1:8000/showcase")
    print("Flowchart available at http://127.0.0.1:8000/flowchart")
    print("=" * 60)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
