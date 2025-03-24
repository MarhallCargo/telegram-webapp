from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Указываем адрес к нашей SQLite-базе в папке проекта
SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./mydatabase.db"

# engine — объект, который знает, как подключаться к базе
engine = create_async_engine(SQLALCHEMY_DATABASE_URL, echo=True)

# sessionmaker — создаёт сессии (подключения) для запросов
AsyncSessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)

# Специальная функция get_db() — FastAPI будет её вызывать через Depends,
# чтобы получить "db" (сессию) в эндпоинте.
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
