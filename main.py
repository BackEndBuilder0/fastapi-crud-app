from typing import List
from fastapi import status, HTTPException, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from app_config import app
from database import database, notes, users
from schemas import Note, NoteIn, UserIn, UserOut
from redis_cache import get_redis_client
import json
from datetime import timedelta
from fastapi.security import OAuth2PasswordRequestForm
from auth import create_access_token, verify_password, get_password_hash, decode_access_token, \
    ACCESS_TOKEN_EXPIRE_MINUTES
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # or DEBUG for more details
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    await database.connect()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# Home Page
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/register-page", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/login-page", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# Form handler for HTML registration
@app.post("/register-form", include_in_schema=False)
async def register_form(request: Request, username: str = Form(...), password: str = Form(...)):
    # check existing user
    query = users.select().where(users.c.username == username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        # re-render registration page with error
        return templates.TemplateResponse("register.html", {"request": request, "error": "Username already registered"})

    # hash password and insert
    hashed_password = get_password_hash(password)
    insert_q = users.insert().values(username=username, hashed_password=hashed_password)
    await database.execute(insert_q)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="user_name",
        value=username,
        httponly=True,
        secure=False,
        samesite="lax"
    )
    return response


# ----------------- Register New User -----------------
@app.post("/register", response_model=UserOut)
async def register_user(user: UserIn):
    # Check if user exists
    query = users.select().where(users.c.username == user.username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    # Hash password
    hashed_password = get_password_hash(user.password)

    # Insert user
    query = users.insert().values(username=user.username, hashed_password=hashed_password)
    user_id = await database.execute(query)

    return {"id": user_id, "username": user.username, "message": f"{user.username} Successfully Registered"}


@app.post("/login-form", include_in_schema=False)
async def login_form(request: Request, username: str = Form(...), password: str = Form(...)):
    query = users.select().where(users.c.username == username)
    db_user = await database.fetch_one(query)

    if not db_user or not verify_password(password, db_user["hashed_password"]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=200
        )

    # set JWT in cookie
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="user_name",
        value=username,
        httponly=True,  # prevents JavaScript access
        secure=False,   # set True if using HTTPS
        samesite="lax"  # helps against CSRF
    )
    return response


# ----------------- Login Endpoint -----------------
@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    query = users.select().where(users.c.username == form_data.username)
    db_user = await database.fetch_one(query)

    if not db_user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    if not verify_password(form_data.password, db_user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    # Create token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": db_user["username"]},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


# Create a note
@app.post("/notes/", response_model=Note, status_code=status.HTTP_201_CREATED)
async def create_note(note: NoteIn, token: dict = Depends(decode_access_token)):
    try:
        logger.info(f"Creating note with text='{note.text}', completed={note.completed}")
        query = notes.insert().values(text=note.text, completed=note.completed)
        last_record_id = await database.execute(query)

        # cache the new note directly
        redis = await get_redis_client()
        note_data = {**note.dict(), "id": last_record_id}
        await redis.set(f"note:{last_record_id}", json.dumps(note_data))
        logger.info(f"Note {last_record_id} created and cached in Redis")

        return note_data
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# Update a note
@app.put("/notes/{note_id}/", response_model=Note, status_code=status.HTTP_200_OK)
async def update_note(note_id: int, payload: NoteIn, token: dict = Depends(decode_access_token)):
    try:
        logger.info(f"Updating note {note_id} with payload={payload.dict()}")
        query = notes.update().where(notes.c.id == note_id).values(
            text=payload.text, completed=payload.completed
        )
        result = await database.execute(query)
        if not result:
            logger.warning(f"Note {note_id} not found for update")
            raise HTTPException(status_code=404, detail=f"Note with id {note_id} not found")
        # update cache for that note
        redis = await get_redis_client()
        note_data = {**payload.dict(), "id": note_id}
        await redis.set(f"note:{note_id}", json.dumps(note_data))
        logger.info(f"Note {note_id} updated and cache refreshed")

        return note_data
    except SQLAlchemyError as e:
        logger.error(f"Database error while updating note {note_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# Read all notes
@app.get("/notes/", response_model=List[Note], status_code=status.HTTP_200_OK)
async def read_notes(skip: int = 0, take: int = 20, token: dict = Depends(decode_access_token)):
    try:
        query = notes.select().offset(skip).limit(take)
        return await database.fetch_all(query)
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# Read single note
@app.get("/notes/{note_id}/", response_model=Note, status_code=status.HTTP_200_OK)
async def read_single_note(note_id: int, token: dict = Depends(decode_access_token)):
    redis = await get_redis_client()
    cached_note = await redis.get(f"note:{note_id}")
    if cached_note:
        logger.info(f"Cache hit for note {note_id}")
        return json.loads(cached_note)
    logger.info(f"Cache miss for note {note_id}, querying DB")
    try:
        query = notes.select().where(notes.c.id == note_id)
        data = await database.fetch_one(query)
        if not data:
            logger.warning(f"No note found in DB with id {note_id}")
            raise HTTPException(status_code=404, detail=f"No data found for ID: {note_id}")

        # add to cache for next time
        await redis.set(f"note:{note_id}", json.dumps(dict(data)))
        logger.info(f"Note {note_id} added to Redis cache")
        return data
    except SQLAlchemyError as e:
        logger.error(f"Database error while reading note {note_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# Delete a note
@app.delete("/notes/{note_id}/", status_code=status.HTTP_200_OK)
async def delete_note(note_id: int, token: dict = Depends(decode_access_token)):
    try:
        logger.info(f"Deleting note {note_id}")
        query = notes.delete().where(notes.c.id == note_id)
        result = await database.execute(query)
        if not result:
            logger.warning(f"Note {note_id} not found for delete")
            raise HTTPException(status_code=404, detail=f"Note with id {note_id} not found")

        # remove that note from cache
        redis = await get_redis_client()
        await redis.delete(f"note:{note_id}")
        logger.info(f"Note {note_id} deleted from DB and removed from cache")

        return {"message": f"Note with id: {note_id} deleted successfully!"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/logout", include_in_schema=False)
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("user_name")  # remove user from cookie
    return response