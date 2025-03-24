from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Order, User  # Импортируем модели, которые нужны для работы
from schemas import OrderCreate, OrderRead
from database import get_db
from routers.auth import get_current_user

router = APIRouter()

@router.post("/", response_model=OrderRead, response_class=ORJSONResponse)
async def create_order(
    order: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Создает новый заказ для авторизованного пользователя."""
    new_order = Order(
        description=order.description,
        user_id=current_user.id
    )
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order)
    return new_order

@router.get("/", response_model=list[OrderRead], response_class=ORJSONResponse)
async def list_orders(
    db: AsyncSession=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Возвращает список заказов текущего пользователя.
    """
    query = select(Order).where(Order.user_id == current_user.id)
    result = await db.execute(query)
    orders = result.scalars().all()
    return orders

@router.delete("/{order_id}", response_class=ORJSONResponse, status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Удаляет заказ с указанным order_id, принадлежащий текущему пользователю.
    Если заказ не найден, возвращается ошибка 404.
    """
    query = select(Order).where(Order.id == order_id, Order.user_id == current_user.id)
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    await db.delete(order)
    await db.commit()
    return


@router.patch("/{order_id}/status", response_model=OrderRead, response_class=ORJSONResponse)
async def update_order_status(
        order_id: int,
        new_status: str,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_user)
):
    # Допустим, обновлять статус могут только администраторы и менеджеры
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ запрещен")

    query = select(Order).where(Order.id == order_id)
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    order.status = new_status
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order
