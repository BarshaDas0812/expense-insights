"""Development entry point: `python run.py`."""
import os

from dotenv import load_dotenv

load_dotenv()  # must run before the app reads environment variables

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
