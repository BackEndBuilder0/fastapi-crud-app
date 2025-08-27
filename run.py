import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",      # <-- replace `main` with the filename where FastAPI app lives
        host="127.0.0.1",
        port=8000,
        reload=True
    )
