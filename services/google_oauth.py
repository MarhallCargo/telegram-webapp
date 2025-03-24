from authlib.integrations.starlette_client import OAuth

oauth = OAuth()

oauth.register(
    name="google",
    client_id="1042758727641-cf5q47aii9ds0at4g5hacjkkmv84dtih.apps.googleusercontent.com",
    client_secret="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",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
    redirect_uri="http://127.0.0.1:8000/auth/google/callback",  # ← ДОБАВЬ ЭТО ЕСЛИ НЕ БЫЛО
)
