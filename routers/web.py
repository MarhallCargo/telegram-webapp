from fastapi import APIRouter, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select
from database import get_db
from passlib.hash import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
import os
import aiofiles
from fastapi import UploadFile, File
from models import Order, OrderFile, TopUpRequest, User  # убедитесь, что OrderFile импортирован
from sqlalchemy.orm import selectinload
from routers.auth import get_current_user
from config import TELEGRAM_BOT_TOKEN, MANAGER_CHAT_ID
import json
from utils import calculate_rub_by_yuan, notify_manager
from datetime import datetime
from sqlalchemy.orm import Session


router = APIRouter()

templates = Jinja2Templates(directory="templates")
TOPUP_RATE = 13.0  # Пример курса (заменишь позже на актуальный)

# Если папки для сохранения файлов еще нет, создадим её
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

@router.post("/order/payment_failed/{order_id}")
async def order_payment_failed(
    order_id: int,
    request: Request,
    reason: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == user["id"]))
    order = result.scalar_one_or_none()

    if not order or order.status != "ожидает оплаты":
        return HTMLResponse("Невозможно обновить статус", status_code=400)

    order.status = "ожидает реквизитов"

    # Можно потом добавить сохранение причины в отдельную таблицу или поле
    if reason:
        print(f"❗ Пользователь {user['username']} указал причину отказа от оплаты: {reason}")

    await db.commit()
    return RedirectResponse(url="/dashboard", status_code=302)

@router.post("/order/upload_payment/{order_id}")
async def upload_order_payment_file(
    order_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order or order.status != "ожидает оплаты":
        return HTMLResponse("Невозможно загрузить файл", status_code=400)

    folder = "uploads"
    os.makedirs(folder, exist_ok=True)
    file_path = f"{folder}/order_payment_{order.id}_{file.filename}"
    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    order.payment_proof_path = file_path
    order.status = "оплачено (на проверке)"
    await db.commit()

    return RedirectResponse("/dashboard", status_code=302)

@router.get("/order/upload_payment/{order_id}", response_class=HTMLResponse)
async def upload_order_payment_form(order_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order or order.status != "ожидает оплаты":
        return HTMLResponse("Заказ не найден или недоступен", status_code=404)

    return templates.TemplateResponse("order_upload_payment.html", {
        "request": request,
        "order": order
    })

@router.post("/order/confirm/{order_id}")
async def confirm_order(order_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    result = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    order = result.scalar_one_or_none()
    if order and order.status == "собран":
        order.status = "ожидает реквизитов"
        await db.commit()
    return RedirectResponse("/dashboard", status_code=302)

@router.post("/profile/edit", response_class=HTMLResponse)
async def edit_profile_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/login", status_code=302)

    query = select(User).where(User.id == user_session["id"])
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Проверка уникальности логина
    if username != user.username:
        check = await db.execute(select(User).where(User.username == username))
        if check.scalar_one_or_none():
            return templates.TemplateResponse("edit_profile.html", {
                "request": request,
                "user": user_session,
                "error": "Логин уже занят"
            })

    user.username = username
    if password:
        user.password = bcrypt.hash(password)

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Обновим сессию
    request.session["user"] = {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "balance": getattr(user, "balance", 0.0)
    }

    return templates.TemplateResponse("edit_profile.html", {
        "request": request,
        "user": request.session["user"],
        "message": "Данные обновлены"
    })

@router.get("/profile/edit", response_class=HTMLResponse)
async def edit_profile_get(request: Request, db: AsyncSession = Depends(get_db)):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("edit_profile.html", {"request": request, "user": user_session})


@router.get("/balance/history", response_class=HTMLResponse)
async def balance_history(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    query = select(TopUpRequest).where(
        TopUpRequest.user_id == user["id"],
        TopUpRequest.status == "confirmed"
    ).order_by(TopUpRequest.created_at.desc())
    result = await db.execute(query)
    history = result.scalars().all()

    return templates.TemplateResponse("balance_history.html", {
        "request": request,
        "history": history,
        "user": user
    })

@router.get("/topup/upload/{topup_id}", response_class=HTMLResponse)
async def upload_payment_form(topup_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    query = select(TopUpRequest).where(TopUpRequest.id == topup_id)
    result = await db.execute(query)
    topup = result.scalar_one_or_none()

    if not topup or topup.status != "waiting_for_payment":
        return HTMLResponse("Заявка не найдена или недоступна", status_code=404)

    return templates.TemplateResponse("upload_payment.html", {
        "request": request,
        "topup": topup
    })

@router.get("/topup/upload/{topup_id}", response_class=HTMLResponse)
async def upload_payment_form(topup_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    query = select(TopUpRequest).where(TopUpRequest.id == topup_id)
    result = await db.execute(query)
    topup = result.scalar_one_or_none()

    if not topup or topup.status != "waiting_for_payment":
        return HTMLResponse("Заявка не найдена или недоступна", status_code=404)

    return templates.TemplateResponse("upload_payment.html", {
        "request": request,
        "topup": topup
    })

@router.get("/balance/topup", response_class=HTMLResponse)
async def topup_balance_form(request: Request):
    with open("config.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)
        current_rate = config_data.get("CNY", 13.0)
    return templates.TemplateResponse("topup_balance.html", {
        "request": request,
        "rate": current_rate
    })

@router.post("/balance/topup", response_class=HTMLResponse)
async def submit_topup(
    request: Request,
    cny_amount: int = Form(...),  # 💴 теперь пользователь вводит юани
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Загружаем текущий базовый курс юаня из config.json
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
            base_cny_rate = config_data.get("CNY", 13.0)
    except (FileNotFoundError, json.JSONDecodeError):
        base_cny_rate = 13.0

    # Вычисляем итоговую сумму в рублях
    rub_amount, used_rate, commission = calculate_rub_by_yuan(cny_amount, base_cny_rate)

    if rub_amount == 0:
        return templates.TemplateResponse("topup_balance.html", {
            "request": request,
            "rate": base_cny_rate,
            "error": "Минимальная сумма — от 350 юаней. Увеличьте сумму."
        })

    # Сохраняем заявку в базу
    new_request = TopUpRequest(
        user_id=current_user.id,
        rub_amount=rub_amount,
        cny_amount=cny_amount,
        status="waiting_for_details"  # 🟡 сразу доступно подтверждение
    )

    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)

    # Уведомление
    commission_rub = rub_amount - (cny_amount * base_cny_rate)
    message = (
        f"🔔 Заявка на пополнение\n"
        f"👤 Пользователь: {current_user.username}\n"
        f"💴 {cny_amount} ¥ ≈ {rub_amount} руб\n"
        f"📊 Курс: {used_rate:.2f} руб/юань (комиссия {commission}%)\n"
        f"💰 Комиссия ≈ {commission_rub:.0f} руб"
    )
    await notify_manager(message)

    return RedirectResponse(url="/dashboard", status_code=302)

@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        db: AsyncSession = Depends(get_db)
):
    # Ищем пользователя в базе данных
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user is None or not bcrypt.verify(password, user.password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный логин или пароль"})

    # Сохраняем данные пользователя в сессии
    request.session["user"] = {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "balance": user.balance
    }

    # Перенаправляем на личный кабинет
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


@router.post("/create_order", response_class=HTMLResponse)
async def create_order_post(
        request: Request,
        links: list[str] = Form(default=[]),
        link_notes: list[str] = Form(default=[]),
        files: list[UploadFile] = File(default=[]),
        file_notes: list[str] = Form(default=[]),
        db: AsyncSession = Depends(get_db)
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Создаём заказ
    new_order = Order(
        description="Собранный заказ из конструктора",
        user_id=user["id"],
        status="новый"
    )
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order)

    # Сохраняем ссылки
    for url, note in zip(links, link_notes):
        if url.strip():
            db.add(OrderLink(order_id=new_order.id, url=url.strip(), note=note.strip()))

    # Сохраняем файлы
    for i, upload in enumerate(files):
        if upload.filename:
            folder = "uploads"
            os.makedirs(folder, exist_ok=True)
            file_path = f"{folder}/{new_order.id}_{upload.filename}"
            async with aiofiles.open(file_path, "wb") as out_file:
                content = await upload.read()
                await out_file.write(content)

            note = file_notes[i] if i < len(file_notes) else ""
            db.add(OrderAttachment(
                order_id=new_order.id,
                file_path=file_path,
                filename=upload.filename,
                note=note.strip()
            ))

    await db.commit()

    return RedirectResponse(url="/dashboard", status_code=302)

@router.post("/topup/upload/{topup_id}")
async def upload_payment_file(
    topup_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    query = select(TopUpRequest).where(TopUpRequest.id == topup_id)
    result = await db.execute(query)
    topup = result.scalar_one_or_none()

    if not topup or topup.status != "waiting_for_payment":
        return HTMLResponse("Заявка не найдена или недоступна", status_code=404)

    # Сохраняем файл
    folder = "uploads"
    os.makedirs(folder, exist_ok=True)
    file_path = f"{folder}/proof_{topup.id}_{file.filename}"
    async with aiofiles.open(file_path, "wb") as out_file:
        content = await file.read()
        await out_file.write(content)

    # Обновляем заявку
    topup.payment_proof_path = file_path
    topup.status = "waiting_for_confirmation"
    db.add(topup)
    await db.commit()

    return RedirectResponse(url="/dashboard", status_code=302)

@router.get("/create_order", response_class=HTMLResponse)
async def create_order_get(request: Request):
    return templates.TemplateResponse("create_order.html", {"request": request})

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.files),
            selectinload(Order.links),
            selectinload(Order.attachments)
        )
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()

    # 💡 Загружаем заявки пользователя на пополнение
    topups_query = select(TopUpRequest).where(TopUpRequest.user_id == user.id).order_by(TopUpRequest.created_at.desc())
    topup_result = await db.execute(topups_query)
    topup_requests = topup_result.scalars().all()
    active_topup_count = len([
        r for r in topup_requests
        if r.status in ("waiting_for_details", "waiting_for_payment", "waiting_for_confirmation")
    ])

    # Загружаем курсы
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        yuan_rate = config.get("CNY", 12.8)
        usd_rate = config.get("USD", 91.5)
    except (FileNotFoundError, json.JSONDecodeError):
        yuan_rate = 13.0
        usd_rate = 90.0

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "topup_requests": topup_requests,
        "yuan_rate": yuan_rate,
        "active_topup_count": active_topup_count,
        "usd_rate": usd_rate,
        "now": datetime.now()
    })

@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@router.get("/profile", response_class=HTMLResponse)
async def get_profile(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user, "error": None})

@router.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    username: str = Form(...),
    password: str = Form(None),
    balance: float = Form(0.0),
    db: AsyncSession = Depends(get_db)
):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Получаем пользователя
    query = select(User).where(User.id == user_session["id"])
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        return templates.TemplateResponse(
            "profile.html",
            {"request": request, "user": user_session, "error": "Пользователь не найден"}
        )

    # 🔒 Запрещаем изменение логина (даже если он был введён вручную)
    if username != user.username:
        return templates.TemplateResponse(
            "profile.html",
            {"request": request, "user": user_session, "error": "Изменение логина запрещено"}
        )

    # 🔒 Проверка пароля
    if password:
        if not (6 <= len(password) <= 20):
            return templates.TemplateResponse(
                "profile.html",
                {"request": request, "user": user_session, "error": "Пароль должен содержать от 6 до 20 символов"}
            )
        user.password = bcrypt.hash(password)

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Обновляем данные сессии
    request.session["user"] = {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "balance": getattr(user, "balance", 0.0)
    }

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

@router.get("/download_file/{file_id}", response_class=FileResponse)
async def download_file(file_id: int, db: AsyncSession = Depends(get_db)):
    # Получаем файл из базы данных по его id
    query = select(OrderFile).where(OrderFile.id == file_id)
    result = await db.execute(query)
    order_file = result.scalar_one_or_none()
    if not order_file:
        return HTMLResponse(content="Файл не найден", status_code=404)
    # Возвращаем файл с указанным путем
    return FileResponse(path=order_file.file_path, filename=order_file.filename)
