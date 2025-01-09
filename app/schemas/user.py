from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    email: EmailStr
    username: str

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    is_active: bool

    class Config:
        from_attributes = True

class UserInDB(UserBase):
    hashed_password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: str | None = None