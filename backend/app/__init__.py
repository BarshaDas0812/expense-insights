"""Application factory."""
import logging

import click
from flask import Flask, send_from_directory

from .config import PROJECT_DIR, load_config
from .db import close_db, connect, init_db, reset_db
from .errors import register_error_handlers

FRONTEND_DIR = PROJECT_DIR / "frontend"


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="/static")
    app.config.update(load_config())
    if config_overrides:
        app.config.update(config_overrides)
    app.json.sort_keys = False
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    init_db(app.config["DATABASE_PATH"])
    app.teardown_appcontext(close_db)
    register_error_handlers(app)

    from .routes import assistant, expenses, meta, stats
    for module in (expenses, stats, assistant, meta):
        app.register_blueprint(module.bp)

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    _register_cli(app)
    return app


def _register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    @click.option("--reset", is_flag=True, help="Drop all data and recreate the schema.")
    def init_db_command(reset):
        """Create the database schema."""
        path = app.config["DATABASE_PATH"]
        if reset:
            reset_db(path)
            click.echo(f"Database reset at {path}")
        else:
            init_db(path)
            click.echo(f"Database ready at {path}")

    @app.cli.command("seed-db")
    @click.option("--count", default=45, show_default=True, help="Number of expenses.")
    @click.option("--reset", is_flag=True, help="Delete existing data first.")
    def seed_db_command(count, reset):
        """Insert deterministic demo expenses."""
        from .seed import seed
        path = app.config["DATABASE_PATH"]
        if reset:
            reset_db(path)
        conn = connect(path)
        try:
            seed(conn, app.config["CLOCK"](), count=count)
        finally:
            conn.close()
        click.echo(f"Inserted {count} demo expenses into {path}")
