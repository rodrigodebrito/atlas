import os

import uvicorn


def main() -> None:
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("agno_api.agent:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
