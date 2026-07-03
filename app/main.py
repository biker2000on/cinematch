import logging

import uvicorn

from .config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

if __name__ == "__main__":
    uvicorn.run("app.web:app", host="0.0.0.0", port=config.PORT, log_level="info")
