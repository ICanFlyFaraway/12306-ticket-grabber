from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    real_name: Mapped[str] = mapped_column(String(32), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class Passenger(Base):
    __tablename__ = "passengers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    id_type: Mapped[str] = mapped_column(String(16), default="1")  # 1=身份证
    id_no: Mapped[str] = mapped_column(String(32), nullable=False)
    passenger_type: Mapped[str] = mapped_column(String(8), default="1")  # 1=成人
    phone: Mapped[str] = mapped_column(String(20), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskConfig(Base):
    __tablename__ = "task_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), default="默认任务")
    from_station: Mapped[str] = mapped_column(String(16), nullable=False)
    from_station_name: Mapped[str] = mapped_column(String(32), default="")
    to_station: Mapped[str] = mapped_column(String(16), nullable=False)
    to_station_name: Mapped[str] = mapped_column(String(32), default="")
    travel_date: Mapped[str] = mapped_column(String(16), nullable=False)
    train_codes: Mapped[str] = mapped_column(Text, default="")  # 逗号分隔
    seat_types: Mapped[str] = mapped_column(Text, default="二等座")
    passenger_ids: Mapped[str] = mapped_column(Text, default="")
    poll_interval: Mapped[float] = mapped_column(Float, default=3.0)
    enable_waitlist: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_submit: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class OrderRecord(Base):
    __tablename__ = "order_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), default="")
    train_code: Mapped[str] = mapped_column(String(16), default="")
    from_station: Mapped[str] = mapped_column(String(32), default="")
    to_station: Mapped[str] = mapped_column(String(32), default="")
    travel_date: Mapped[str] = mapped_column(String(16), default="")
    seat_type: Mapped[str] = mapped_column(String(16), default="")
    passengers: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(Text, default="")


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    pinyin: Mapped[str] = mapped_column(String(32), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
