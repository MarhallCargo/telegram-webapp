from pydantic import BaseModel
from typing import Optional
from datetime import datetime
# Схемы для пользователя
class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserRead(UserBase):
    id: int

    class Config:
        orm_mode = True  # Если используете Pydantic V1; для V2 используйте: from_attributes = True

# Схемы для заказа
class OrderBase(BaseModel):
    description: str

class OrderCreate(OrderBase):
    pass

class OrderRead(OrderBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True
class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None

    class Config:
        orm_mode = True
