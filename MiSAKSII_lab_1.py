from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel
from typing import List, Optional
import sqlalchemy
import databases
from datetime import date
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Request

templates = Jinja2Templates(directory="templates")

DATABASE_URL = "sqlite:///./forum.db"

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# Таблицы
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("login", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password", sqlalchemy.String),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("phone", sqlalchemy.String),
    sqlalchemy.Column("email", sqlalchemy.String),
)

categories = sqlalchemy.Table(
    "categories",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
)

threads = sqlalchemy.Table(
    "threads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("title", sqlalchemy.String),
    sqlalchemy.Column("author_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("date", sqlalchemy.String),
    sqlalchemy.Column("status", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("category_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("categories.id")),
    sqlalchemy.Column("pinned", sqlalchemy.Boolean, default=False),
)

posts = sqlalchemy.Table(
    "posts",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("thread_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("threads.id")),
    sqlalchemy.Column("author_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("date", sqlalchemy.String),
    sqlalchemy.Column("content", sqlalchemy.Text),
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

app = FastAPI()

# Pydantic модели
class UserCreate(BaseModel):
    login: str
    password: str
    name: str
    phone: str
    email: str

class UserUpdate(BaseModel):
    login: str
    old_pass: str
    new_pass: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class UserDelete(BaseModel):
    password: str

class ThreadCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category_id: Optional[int] = None

class ThreadUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class ThreadMove(BaseModel):
    category_id: int

class PostCreate(BaseModel):
    content: str

class PostUpdate(BaseModel):
    content: str

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

# Вспомогательные функции
async def get_user_by_login(login: str):
    return await database.fetch_one(users.select().where(users.c.login == login))

async def get_user_by_id(user_id: int):
    return await database.fetch_one(users.select().where(users.c.id == user_id))

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# 1. Работа с пользователями

# Вход / Войти
@app.get("/USER/login")
async def login_user(Login: str = Query(...), Password: str = Query(...)):
    user = await get_user_by_login(Login)
    if user and user['password'] == Password:
        return {"status": "success", "auth_code": "dummy_token"}
    raise HTTPException(status_code=401, detail="Unauthorized")

# Регистрация нового пользователя
@app.put("/USER")
async def register_user(user: UserCreate):
    existing = await get_user_by_login(user.login)
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    await database.execute(users.insert().values(
        login=user.login,
        password=user.password,
        name=user.name,
        phone=user.phone,
        email=user.email
    ))
    return {"status": "registered"}

@app.get("/USER")
async def get_all_users():
    query = users.select()
    all_users = await database.fetch_all(query)
    return [dict(user) for user in all_users]

# Корректировка свойств пользователя
@app.post("/USER")
async def update_user(user: UserUpdate):
    db_user = await get_user_by_login(user.login)
    if not db_user or db_user['password'] != user.old_pass:
        raise HTTPException(status_code=403, detail="Forbidden")
    update_data = {}
    if user.new_pass:
        update_data['password'] = user.new_pass
    if user.name:
        update_data['name'] = user.name
    if user.phone:
        update_data['phone'] = user.phone
    if user.email:
        update_data['email'] = user.email
    if update_data:
        await database.execute(users.update().where(users.c.id == db_user['id']).values(**update_data))
    return {"status": "updated"}

# Удаление собственного аккаунта
@app.delete("/USER")
async def delete_user(Password: str = Query(...), login: str = Query(...)):
    user = await get_user_by_login(login)
    if not user or user['password'] != Password:
        raise HTTPException(status_code=403, detail="Forbidden")
    await database.execute(users.delete().where(users.c.id == user['id']))
    return {"status": "deleted"}

# 2. Работа с форумными темами (THREAD)

# Получить список тем
@app.get("/THREAD")
async def get_threads():
    query = threads.select()
    return await database.fetch_all(query)

# Получить детальную информацию о теме {ID}
@app.get("/THREAD/{id}")
async def get_thread(id: int = Path(...)):
    thread = await database.fetch_one(threads.select().where(threads.c.id == id))
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    # Получим посты
    thread_posts = await database.fetch_all(posts.select().where(posts.c.thread_id == id))
    thread_dict = dict(thread)
    thread_dict['Posts'] = [dict(p) for p in thread_posts]
    return thread_dict

# Создать новую тему
@app.post("/THREAD")
async def create_thread(thread: ThreadCreate):
    author_id = 1  # В реальности — авторизация
    date_str = date.today().isoformat()
    query = threads.insert().values(
        title=thread.title,
        description=thread.description,
        category_id=thread.category_id,
        date=date_str,
        author_id=author_id,
        status="Открыта",
        pinned=False
    )
    thread_id = await database.execute(query)
    return {"id": thread_id}

# Обновить тему {ID}
@app.put("/THREAD/{id}")
async def update_thread(id: int, thread: ThreadUpdate):
    existing = await database.fetch_one(threads.select().where(threads.c.id == id))
    if not existing:
        raise HTTPException(status_code=404, detail="Thread not found")
    update_data = {k: v for k, v in thread.dict(exclude_unset=True).items()}
    await database.execute(threads.update().where(threads.c.id == id).values(**update_data))
    return {"status": "updated"}

# Удалить тему {ID}
@app.delete("/THREAD/{id}")
async def delete_thread(id: int):
    await database.execute(threads.delete().where(threads.c.id == id))
    return {"status": "deleted"}

# Закрепить / Открепить тему {ID}
@app.put("/THREAD/{id}/pin")
async def pin_thread(id: int):
    await database.execute(threads.update().where(threads.c.id == id).values(pinned=True))
    return {"status": "pinned"}

# Переместить тему в другую категорию {ID}
@app.put("/THREAD/{id}/move")
async def move_thread(id: int, move: ThreadMove):
    category = await database.fetch_one(categories.select().where(categories.c.id == move.category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    await database.execute(threads.update().where(threads.c.id == id).values(category_id=move.category_id))
    return {"status": "moved"}

# 3. Работа с сообщениями (POST)

# Получить список сообщений в теме {ID}
@app.get("/THREAD/{id}/POSTS")
async def get_posts(id: int):
    thread = await database.fetch_one(threads.select().where(threads.c.id == id))
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    all_posts = await database.fetch_all(posts.select().where(posts.c.thread_id == id))
    return [dict(p) for p in all_posts]

# Создать новое сообщение в теме {ID}
@app.post("/THREAD/{id}/POSTS")
async def create_post(id: int, post: PostCreate):
    author_id = 1  # В реальности — авторизация
    date_str = date.today().isoformat()
    thread = await database.fetch_one(threads.select().where(threads.c.id == id))
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    await database.execute(posts.insert().values(
        thread_id=id,
        author_id=author_id,
        date=date_str,
        content=post.content
    ))
    return {"status": "created"}

# Обновить сообщение {ID}
@app.put("/POST/{id}")
async def update_post(id: int, post: PostUpdate):
    existing = await database.fetch_one(posts.select().where(posts.c.id == id))
    if not existing:
        raise HTTPException(status_code=404, detail="Post not found")
    await database.execute(posts.update().where(posts.c.id == id).values(content=post.content))
    return {"status": "updated"}

# Удалить сообщение {ID}
@app.delete("/POST/{id}")
async def delete_post(id: int):
    await database.execute(posts.delete().where(posts.c.id == id))
    return {"status": "deleted"}

# 4. Работа с категориями (CATEGORY)

# Получить список категорий
@app.get("/CATEGORY")
async def get_categories():
    return await database.fetch_all(categories.select())

# Получить информацию о категории {ID}
@app.get("/CATEGORY/{id}")
async def get_category(id: int):
    category = await database.fetch_one(categories.select().where(categories.c.id == id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return dict(category)

# Создать категорию
@app.post("/CATEGORY")
async def create_category(cat: CategoryCreate):
    await database.execute(categories.insert().values(
        name=cat.name,
        description=cat.description
    ))
    return {"status": "created"}

# Обновить категорию {ID}
@app.put("/CATEGORY/{id}")
async def update_category(id: int, cat: CategoryUpdate):
    existing = await database.fetch_one(categories.select().where(categories.c.id == id))
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    data = {k: v for k, v in cat.dict(exclude_unset=True).items()}
    await database.execute(categories.update().where(categories.c.id == id).values(**data))
    return {"status": "updated"}

# Удалить категорию {ID}
@app.delete("/CATEGORY/{id}")
async def delete_category(id: int):
    await database.execute(categories.delete().where(categories.c.id == id))
    return {"status": "deleted"}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    # Добавляем получение пользователей, чтобы избежать ошибок в шаблоне
    all_threads = await database.fetch_all(threads.select())
    all_cats = await database.fetch_all(categories.select())
    all_users = await database.fetch_all(users.select()) # Добавлено
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "threads": all_threads,
        "categories": all_cats,
        "users_list": all_users # Теперь это безопасно использовать в HTML
    })
