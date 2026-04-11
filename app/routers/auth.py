from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import Optional

from app.db.database import get_db
from app.model.db_models import User, Firm
from app.services.auth_service import hash_password, verify_password, create_access_token, decode_token

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    firm_name: str
    full_name: str
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      int
    user_name:    str
    email:        str
    firm_name:    str
    role:         str
    plan_tier:    str
    subscription_status: str
    trial_ends_at: Optional[str]


# ── Dependency: resolve current user from Bearer token ───────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db:    Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload.get("sub", 0))).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    # Duplicate checks
    if db.query(User).filter(User.email == req.email.lower().strip()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(Firm).filter(Firm.name == req.firm_name.strip()).first():
        raise HTTPException(status_code=400, detail="Firm name already taken")

    # Create firm
    firm = Firm(name=req.firm_name.strip())
    db.add(firm)
    db.flush()  # populate firm.id before referencing in User

    # Create owner user
    user = User(
        email           = req.email.lower().strip(),
        full_name       = req.full_name.strip(),
        hashed_password = hash_password(req.password),
        firm_id         = firm.id,
        role            = "owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(firm)

    token = create_access_token({"sub": str(user.id)})
    return _build_response(token, user, firm)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive. Contact your firm admin.")

    token = create_access_token({"sub": str(user.id)})
    return _build_response(token, user, user.firm)


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    firm = current_user.firm
    return {
        "id":                  current_user.id,
        "email":               current_user.email,
        "full_name":           current_user.full_name,
        "role":                current_user.role,
        "firm_name":           firm.name,
        "plan_tier":           firm.plan_tier,
        "subscription_status": firm.subscription_status,
        "trial_ends_at":       firm.trial_ends_at.isoformat() if firm.trial_ends_at else None,
    }


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_response(token: str, user: User, firm: Firm) -> TokenResponse:
    return TokenResponse(
        access_token        = token,
        user_id             = user.id,
        user_name           = user.full_name,
        email               = user.email,
        firm_name           = firm.name,
        role                = user.role,
        plan_tier           = firm.plan_tier,
        subscription_status = firm.subscription_status,
        trial_ends_at       = firm.trial_ends_at.isoformat() if firm.trial_ends_at else None,
    )
