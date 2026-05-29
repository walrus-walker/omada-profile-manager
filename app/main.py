import logging

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth, database
from app.config import get_settings
from app.templates_instance import templates
from app.routes import dashboard, devices, profiles, settings as settings_router
from app.routes import schedules as schedules_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(title="Net Profile Manager", docs_url=None, redoc_url=None)

_settings = get_settings()

app.add_middleware(SessionMiddleware, secret_key=_settings.APP_SECRET_KEY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register dark_mode as a callable global so every template can use dark_mode()
templates.env.globals["dark_mode"] = lambda: database.get_app_setting("dark_mode", "0") == "1"


@app.on_event("startup")
def startup():
    database.init_db()
    from app.worker import start_worker
    start_worker()


# --- Auth routes ---

@app.get("/login")
def login_page(request: Request):
    if auth.is_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"flash_messages": auth.pop_flash(request)},
    )


@app.post("/login")
def login(request: Request, pin: str = Form(...)):
    s = get_settings()
    if auth.verify_pin(pin, s.APP_ADMIN_PIN):
        request.session["authenticated"] = True
        return RedirectResponse(url="/dashboard", status_code=302)

    auth.add_flash(request, "Incorrect PIN. Please try again.", "error")
    return RedirectResponse(url="/login", status_code=302)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


# --- Feature routers ---

app.include_router(dashboard.router)
app.include_router(devices.router)
app.include_router(profiles.router)
app.include_router(settings_router.router)
app.include_router(schedules_router.router)
