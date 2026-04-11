import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base


class Firm(Base):
    __tablename__ = "firms"

    id                   = Column(Integer, primary_key=True, index=True)
    name                 = Column(String, unique=True, index=True, nullable=False)
    plan_tier            = Column(String, default="trial")          # trial / professional / enterprise
    seats_allowed        = Column(Integer, default=3)
    subscription_status  = Column(String, default="trial")          # trial / active / expired
    trial_ends_at        = Column(DateTime, default=lambda: datetime.datetime.utcnow() + datetime.timedelta(days=14))
    created_at           = Column(DateTime, default=datetime.datetime.utcnow)

    users = relationship("User", back_populates="firm")


class User(Base):
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True, index=True)
    email            = Column(String, unique=True, index=True, nullable=False)
    full_name        = Column(String, nullable=False)
    hashed_password  = Column(String, nullable=False)
    firm_id          = Column(Integer, ForeignKey("firms.id"), nullable=False)
    role             = Column(String, default="owner")   # owner / admin / member
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=datetime.datetime.utcnow)

    firm = relationship("Firm", back_populates="users")
