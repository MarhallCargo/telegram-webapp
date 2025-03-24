from datetime import datetime, timedelta, timezone
from typing import Optional
from schemas import UserUpdate  # убедитесь, что импорт добавлен
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import ORJSONResponse
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from passlib.context import CryptContext
from passlib.hash import bcrypt
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi.responses import HTMLResponse
from schemas import UserCreate, UserRead
from database import get_db
from models import User
from fastapi.templating import Jinja2Templates
from services.google_oauth import oauth
from fastapi.responses import PlainTextResponse, RedirectResponse

router = APIRouter()
templates = Jinja2Templates(directory="templates")
bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------
# Конфигурация для JWT
# ---------------------------
SECRET_KEY = "YOUR_SECRET_KEY"  # Замените на свой сложный и секретный ключ
ALGORITHM = "HS256"             # Алгоритм подписи
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # Время жизни токена в минутах

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Создает JWT-токен.
    Принимает словарь data (например, {"sub": username}) и время жизни токена.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        print("GOOGLE TOKEN:", token)

        user_info = None

        try:
            user_info = await oauth.google.parse_id_token(request, token)
            print("User info from ID token:", user_info)
        except Exception as e:
            print("No id_token, fallback to userinfo. Error:", e)

        if not user_info:
            resp = await oauth.google.get("https://www.googleapis.com/oauth2/v2/userinfo", token=token)
            user_info = resp.json()
            print("User info from userinfo endpoint:", user_info)

        if not user_info or "email" not in user_info:
            return PlainTextResponse("Ошибка получения данных пользователя", status_code=400)

        email = user_info["email"]
        name = user_info.get("name", email.split("@")[0])

        existing_user = await db.execute(select(User).where(User.username == email))
        user = existing_user.scalar_one_or_none()

        if not user:
            user = User(username=email, password="", role="user")
            db.add(user)
            await db.commit()
            await db.refresh(user)

        request.session["user"] = {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "balance": getattr(user, "balance", 0.0)
        }
        return RedirectResponse(url="/dashboard")

    except Exception as e:
        print("GOOGLE CALLBACK ERROR:", e)
        return PlainTextResponse("Ошибка авторизации через Google", status_code=500)

@router.post("/token", response_class=ORJSONResponse)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),  # Извлекает form-data с полями "username" и "password"
    db: AsyncSession = Depends(get_db)
):
    # 1. Ищем пользователя по username
    query = select(User).where(User.username == form_data.username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    # 2. Проверяем, что введённый пароль соответствует хэшированному паролю из базы
    if not bcrypt.verify(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    # 3. Создаем JWT-токен
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires
    )

    # 4. Возвращаем токен клиенту
    return {"access_token": access_token, "token_type": "bearer"}

# ---------------------------
# Зависимость для получения текущего пользователя
# ---------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    # Извлекаем данные пользователя из сессии
    user_session = request.session.get("user")
    if not user_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Получаем пользователя из базы по его id (сохранённому в сессии)
    query = select(User).where(User.id == user_session["id"])
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user

# ---------------------------
# Эндпоинт для получения данных текущего пользователя
# ---------------------------
@router.get("/me", response_model=UserRead, response_class=ORJSONResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.patch("/me", response_model=UserRead, response_class=ORJSONResponse)
async def update_profile(
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Обновляет профиль текущего пользователя.
    Можно изменить username и/или password.
    """
    # Если передан новый username, проверяем его уникальность
    if user_update.username:
        query = select(User).where(User.username == user_update.username, User.id != current_user.id)
        result = await db.execute(query)
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
        current_user.username = user_update.username

    # Если передан новый пароль – хэшируем и обновляем
    if user_update.password:
        current_user.password = bcrypt.hash(user_update.password)

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    # Отображаем форму регистрации без ошибок
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@router.post("/register", response_class=HTMLResponse)
async def register_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        db: AsyncSession = Depends(get_db)
):
    # Проверяем, существует ли уже пользователь с данным логином
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()
    if existing_user:
        # Если пользователь найден, возвращаем форму с сообщением об ошибке
        return templates.TemplateResponse("register.html",
                                          {"request": request, "error": "Пользователь с таким именем уже существует"})

    # Хэшируем пароль с помощью bcrypt

    hashed_password = bcrypt_context.hash(password)

    # Создаем нового пользователя с ролью "user"
    new_user = User(username=username, password=hashed_password, role="user")
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # После регистрации перенаправляем на страницу логина
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "username": ""})


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Пользователь не существует",
            "username": username
        })

    if not bcrypt_context.verify(password, user.password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Неверный пароль",
            "username": username
        })

    # Записываем в сессию пользователя (если используется SessionMiddleware)
    request.session["user"] = {"id": user.id, "username": user.username}

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

@router.post("/telegram_register", response_class=ORJSONResponse)
async def telegram_register(
    request: Request,
    telegram_id: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    # Проверяем, зарегистрирован ли уже пользователь с таким Telegram ID
    query = select(User).where(User.telegram_id == telegram_id)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()

    if existing_user:
        return {"message": "Пользователь уже зарегистрирован", "username": existing_user.username}

    # Хэшируем пароль
    hashed_password = bcrypt_context.hash(password)

    # Создаём нового пользователя
    new_user = User(
        username=username,
        password=hashed_password,
        role="user",
        telegram_id=telegram_id
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return {"message": "Пользователь успешно зарегистрирован", "username": new_user.username}
