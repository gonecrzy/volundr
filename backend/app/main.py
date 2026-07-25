from fastapi import FastAPI

app = FastAPI(title="Volundr API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
