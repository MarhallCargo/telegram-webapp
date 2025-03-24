from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import ORJSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models import Order, User, TopUpRequest
from routers.auth import get_current_user
from fastapi.templating import Jinja2Templates
from schemas import OrderRead
from fastapi.responses import JSONResponse
from sqlalchemy.orm import selectinload
import json
import os

router = APIRouter()
templates = Jinja2Templates(directory="templates")
CONFIG_FILE_PATH = "config.json"

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if user.get("role") != "admin":
        return HTMLResponse(content="Доступ запрещен", status_code=403)

    # Подсчёты по статусам
    new_orders = await db.execute(select(Order).where(Order.status == "новый"))
    processing_orders = await db.execute(select(Order).where(Order.status == "в обработке"))
    shipping_orders = await db.execute(select(Order).where(Order.status == "в пути"))
    waiting_details_orders = await db.execute(select(Order).where(Order.status == "ожидает реквизитов"))
    waiting_payment_orders = await db.execute(select(Order).where(Order.status == "ожидает оплаты"))
    confirming_orders = await db.execute(
        select(Order).where(Order.status.in_(["подтверждение платежа", "оплачено (на проверке)"]))
    )

    ready_orders = await db.execute(select(Order).where(Order.status == "собран"))

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "user": user,
        "new_count": len(new_orders.scalars().all()),
        "processing_count": len(processing_orders.scalars().all()),
        "shipping_count": len(shipping_orders.scalars().all()),
        "waiting_details_count": len(waiting_details_orders.scalars().all()),
        "waiting_payment_count": len(waiting_payment_orders.scalars().all()),
        "confirming_count": len(confirming_orders.scalars().all()),
        "ready_orders_count": len(ready_orders.scalars().all())


    })

@router.get("/orders/waiting_payment", response_class=HTMLResponse)
async def admin_waiting_payment_orders(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.files))
        .where(Order.status == "ожидает оплаты")
    )
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "💳 Ожидают оплаты"
    })

@router.get("/orders/ready", response_class=HTMLResponse)
async def admin_ready_orders(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Order).options(selectinload(Order.files)).where(Order.status == "собран")
    )
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "📦 Собранные заказы"
    })

@router.post("/order/reject_payment/{order_id}")
async def reject_order_payment(order_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    order.status = "ожидает реквизитов"
    await db.commit()
    return RedirectResponse(url="/admin/orders/confirming", status_code=302)


@router.post("/order/confirm_payment/{order_id}")
async def confirm_order_payment(order_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    order.status = "в работе"
    order.is_chat_open = False
    await db.commit()
    return RedirectResponse(url="/admin/orders/confirming", status_code=302)


@router.get("/orders/confirming", response_class=HTMLResponse)
async def orders_confirming(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.files))
        .where(Order.status.in_(["подтверждение платежа", "оплачено (на проверке)"]))
    )
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "🔍 Подтверждение платежей"
    })

@router.post("/order/set_payment_details/{order_id}")
async def set_payment_details(
    order_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    details = form.get("details")

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if order and order.status == "ожидает реквизитов":
        order.payment_details = details
        order.status = "ожидает оплаты"
        await db.commit()

    return RedirectResponse("/admin/orders/waiting_details", status_code=302)

@router.post("/order/send/{order_id}")
async def send_order(order_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    track_code = form.get("track_code")

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if order and track_code:
        date_str = datetime.now().strftime("%d.%m.%Y")
        order.description = f"{track_code} от {date_str}"
        order.status = "в путь"
        await db.commit()

    return RedirectResponse(url="/admin/orders/processing", status_code=302)

@router.get("/orders/shipping", response_class=HTMLResponse)
async def admin_shipping_orders(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Order).options(selectinload(Order.files)).where(Order.status == "в пути")
    )
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "🚚 Грузы в пути"
    })

@router.get("/orders/processing", response_class=HTMLResponse)
async def admin_processing_orders(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Order).options(selectinload(Order.files)).where(Order.status == "в обработке")
    )
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "🛠 Заказы в обработке"
    })

@router.get("/orders/new", response_class=HTMLResponse)
async def admin_new_orders(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Order).options(selectinload(Order.files)).where(Order.status == "новый")
    )
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "📥 Новые заказы"
    })

@router.post("/order/delete/{order_id}")
async def delete_order(order_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order:
        await db.delete(order)
        await db.commit()
    return RedirectResponse("/admin/dashboard", status_code=302)

@router.post("/order/ready/{order_id}")
async def ready_order(order_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order:
        order.status = "собран"
        await db.commit()
    return RedirectResponse("/admin/dashboard", status_code=302)

@router.post("/order/accept/{order_id}")
async def accept_order(order_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order:
        order.status = "в обработке"
        await db.commit()
    return RedirectResponse("/admin/dashboard", status_code=302)

def admin_required(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have sufficient privileges"
        )
    return user

@router.post("/set_usd_rate")
async def set_usd_rate(request: Request, new_usd_rate: float = Form(...)):
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config_data = {}

    config_data["USD"] = round(new_usd_rate, 2)

    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)

    return RedirectResponse(url="/admin/dashboard", status_code=302)

@router.get("/topups", response_class=HTMLResponse)
async def view_topups(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        return HTMLResponse("Доступ запрещен", status_code=403)

    # Подгружаем заявки + связанные данные пользователей
    query = select(TopUpRequest).where(
        TopUpRequest.status.in_([
            "waiting_for_details", "waiting_for_payment", "waiting_for_confirmation"
        ])
    ).options(selectinload(TopUpRequest.user))

    result = await db.execute(query)
    topups = result.scalars().all()

    return templates.TemplateResponse("admin_topups.html", {
        "request": request,
        "topups": topups,
        "user": current_user
    })

@router.post("/topups/{request_id}/add_details")
async def add_payment_details(request_id: int, payment_details: str = Form(...), db: AsyncSession = Depends(get_db)):
    query = select(TopUpRequest).where(TopUpRequest.id == request_id)
    result = await db.execute(query)
    topup = result.scalar_one_or_none()

    if topup:
        topup.payment_details = payment_details

        # Если ещё не перешли на стадию "ожидание оплаты", обновим статус
        if topup.status == "waiting_for_details":
            topup.status = "waiting_for_payment"

        db.add(topup)
        await db.commit()

    return RedirectResponse(url="/admin/topups", status_code=302)

@router.post("/set_balance/{user_id}", response_class=HTMLResponse)
async def set_balance(user_id: int, request: Request, new_balance: float = Form(...), db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        return HTMLResponse("Пользователь не найден", status_code=404)
    user.balance = new_balance
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)

@router.get("/set_balance/{user_id}", response_class=HTMLResponse)
async def set_balance_get(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return HTMLResponse("Пользователь не найден", status_code=404)

    return templates.TemplateResponse("admin_set_balance.html", {
        "request": request,
        "user": user
    })

@router.post("/topups/{request_id}/confirm")
async def confirm_topup(request_id: int, db: AsyncSession = Depends(get_db)):
    query = select(TopUpRequest).where(TopUpRequest.id == request_id).options(selectinload(TopUpRequest.user))
    result = await db.execute(query)
    topup = result.scalar_one_or_none()

    if topup and topup.status == "waiting_for_confirmation":
        user = topup.user
        user.balance += topup.cny_amount
        topup.status = "confirmed"
        db.add_all([topup, user])
        await db.commit()
    return RedirectResponse(url="/admin/topups", status_code=302)

@router.post("/topups/{request_id}/reject")
async def reject_topup(request_id: int, db: AsyncSession = Depends(get_db)):
    query = select(TopUpRequest).where(TopUpRequest.id == request_id)
    result = await db.execute(query)
    topup = result.scalar_one_or_none()

    if topup and topup.status in ["waiting_for_payment", "waiting_for_confirmation"]:
        topup.status = "rejected"
        db.add(topup)
        await db.commit()
    return RedirectResponse(url="/admin/topups", status_code=302)

@router.post("/set_yuan_rate")
async def set_yuan_rate(request: Request, new_rate: float = Form(...)):
    # Загружаем текущую конфигурацию
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    else:
        config_data = {}

    # Обновляем значение CNY
    config_data["CNY"] = new_rate

    # Сохраняем обратно в файл
    with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)

    # Перенаправляем обратно в кабинет админа
    return RedirectResponse(url="/admin/dashboard", status_code=302)

@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int, db: AsyncSession = Depends(get_db),
                      current_user=Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ запрещен")

    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    target_user = result.scalar_one_or_none()  # Переименовали переменную
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Загружаем заказы пользователя с подгрузкой связанных файлов
    orders_query = select(Order).where(Order.user_id == user_id).options(selectinload(Order.files))
    orders_result = await db.execute(orders_query)
    orders = orders_result.scalars().all()
    topups_query = select(TopUpRequest).where(TopUpRequest.user_id == user_id).order_by(TopUpRequest.created_at.desc())
    topups_result = await db.execute(topups_query)
    topups = topups_result.scalars().all()

    return templates.TemplateResponse("admin_user_detail.html", {
        "request": request,
        "user": current_user,
        "user_detail": target_user,  # Передаем под новым именем
        "orders": orders,
        "topups": topups  #
    })

@router.get("/users", response_class=HTMLResponse)
async def list_users(request: Request, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    # Проверяем, что текущий пользователь - администратор
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ запрещен")

    query = select(User)
    result = await db.execute(query)
    users = result.scalars().all()
    return templates.TemplateResponse("admin_users.html", {"request": request, "user": current_user, "users": users})

@router.get("/orders", response_class=ORJSONResponse)
async def get_all_orders(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(admin_required)
):
    """
    Возвращает список всех заказов в системе (только для администраторов).
    """
    query = select(Order)
    result = await db.execute(query)
    orders = result.scalars().all()
    return orders

@router.get("/orders/new", response_class=HTMLResponse)
async def admin_new_orders(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Order).options(selectinload(Order.files)).where(Order.status == "новый")
    )
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "📥 Новые заказы"
    })

@router.get("/orders/waiting_details", response_class=HTMLResponse)
async def admin_waiting_details(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user or user.get("role") != "admin":
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(select(Order).where(Order.status == "ожидает реквизитов"))
    orders = result.scalars().all()

    return templates.TemplateResponse("admin_orders_details.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "title": "📄 Заказы, ожидающие реквизитов"
    })

@router.post("/orders/{order_id}/status", response_class=JSONResponse)
async def update_order_status(
        order_id: int,
        new_status: str = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Проверяем, имеет ли пользователь право обновлять статус заказа
    if current_user.role not in ["admin", "manager"]:
        return JSONResponse(status_code=403, content={"message": "Доступ запрещен"})

    # Ищем заказ по ID
    query = select(Order).where(Order.id == order_id)
    result = await db.execute(query)
    order = result.scalar_one_or_none()

    if not order:
        return JSONResponse(status_code=404, content={"message": "Заказ не найден"})

    # Обновляем статус заказа
    order.status = new_status
    db.add(order)
    await db.commit()
    await db.refresh(order)

    return JSONResponse(status_code=200, content={"message": "Статус изменён", "new_status": order.status})
