import uvicorn

from app.runtime import run

if __name__ == "__main__":
    run(
        uvicorn.Server(
            uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, access_log=False, proxy_headers=False)
        ).serve()
    )
