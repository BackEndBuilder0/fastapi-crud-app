from datetime import datetime, timedelta
from typing import Optional
import os

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# Secret key (in real world, keep in Azure Key Vault or env variables)
SECRET_KEY = os.environ.get('secret_key')
# SECRET_KEY = 'huigytdrsetdyfugihojpi657890'
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = os.environ.get('access_token_expire_minute', 30)

# Password hashing context (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# FastAPI helper for OAuth2 (extracts token from requests)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", scheme_name="Bearer")


# ----------------- Utility Functions -----------------

# 1. Hash a password
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# 2. Verify plain password against hashed password
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# 3. Create JWT token
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})  # add expiry claim
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# 4. Decode JWT token and validate
def decode_access_token(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
