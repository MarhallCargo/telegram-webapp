from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from routers import auth, orders, admin, web, chat
from fastapi.staticfiles import StaticFiles
from routers import admin

app = FastAPI()

# Подключаем роутеры
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(orders.router, prefix="/orders", tags=["orders"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(web.router, prefix="", tags=["web"])
app.include_router(chat.router, prefix="", tags=["chat"])
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.include_router(admin.router, prefix="/admin", tags=["admin"])
# Добавляем поддержку сессий
app.add_middleware(SessionMiddleware, secret_key="YOUR_SESSION_SECRET_KEY")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# Главная страница (HTML)
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "username": "Гость", "orders": []})
