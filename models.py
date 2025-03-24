from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
from sqlalchemy import Float
from sqlalchemy import Text

Base = declarative_base()

class OrderLink(Base):
    __tablename__ = "order_links"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    url = Column(String, nullable=False)
    note = Column(Text)

    order = relationship("Order", back_populates="links")


class OrderAttachment(Base):
    __tablename__ = "order_attachments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    note = Column(Text)

    order = relationship("Order", back_populates="attachments")

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String, default="user")
    balance = Column(Float, default=0.0)  # Новое поле для баланса
    orders = relationship("Order", back_populates="user", cascade="all, delete")
    telegram_id = Column(String, unique=True, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String, default="новый")  # Добавляем поле статуса с дефолтным значением "новый"
    user = relationship("User", back_populates="orders")
    links = relationship("OrderLink", back_populates="order", cascade="all, delete-orphan")
    attachments = relationship("OrderAttachment", back_populates="order", cascade="all, delete-orphan")
    payment_details = Column(String, nullable=True)
    is_chat_open = Column(Boolean, default=False)

class OrderFile(Base):
    __tablename__ = "order_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    order_id = Column(Integer, ForeignKey("orders.id"))
    order = relationship("Order", back_populates="files")


# Добавляем связь в модель Order:
Order.files = relationship("OrderFile", back_populates="order", cascade="all, delete")

class TopUpRequest(Base):
    __tablename__ = "topup_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    rub_amount = Column(Float, nullable=False)
    cny_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    status = Column(String, default="waiting_for_details")  # начальное состояние
    payment_details = Column(String, nullable=True)  # реквизиты от менеджера
    payment_proof_path = Column(String, nullable=True)  # путь к файлу клиента

    user = relationship("User", backref="topup_requests")
