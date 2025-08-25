from typing import List
from fastapi import status, HTTPException
import logging
from app_config import app
from database import database, notes
from schemas import Note, NoteIn
logging.basicConfig(
    level=logging.DEBUG,  # or DEBUG for more details
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
@app.on_event("startup")
async def startup():
    await database.connect()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# Create a note
@app.post("/notes/", response_model=Note, status_code=status.HTTP_201_CREATED)
async def create_note(note: NoteIn):
    query = notes.insert().values(text=note.text, completed=note.completed)
    last_record_id = await database.execute(query)
    return {**note.dict(), "id": last_record_id}


# Update a note
@app.put("/notes/{note_id}/", response_model=Note, status_code=status.HTTP_200_OK)
async def update_note(note_id: int, payload: NoteIn):
    query = notes.update().where(notes.c.id == note_id).values(
        text=payload.text, completed=payload.completed
    )
    await database.execute(query)
    return {**payload.dict(), "id": note_id}


# Read all notes
@app.get("/notes/", response_model=List[Note], status_code=status.HTTP_200_OK)
async def read_notes(skip: int = 0, take: int = 20):
    query = notes.select().offset(skip).limit(take)
    return await database.fetch_all(query)


# Read single note
@app.get("/notes/{note_id}/", response_model=Note, status_code=status.HTTP_200_OK)
async def read_single_note(note_id: int):
    print(f"➡️ Fetching note with ID: {note_id}")
    query = notes.select().where(notes.c.id == note_id)
    data = await database.fetch_one(query)
    if not data:
        print(f"⚠️ No data found for ID: {note_id}")
        raise HTTPException(
            status_code=404,
            detail=f"No data found for ID: {note_id}"
        )
    print(f"✅ Found note: {data}")
    return data


# Delete a note
@app.delete("/notes/{note_id}/", status_code=status.HTTP_200_OK)
async def delete_note(note_id: int):
    query = notes.delete().where(notes.c.id == note_id)
    await database.execute(query)
    return {"message": f"Note with id: {note_id} deleted successfully!"}
