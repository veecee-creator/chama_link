# Enable Google sign-in

1. Install project dependencies with `pip install -r requirements.txt`.
2. Create a Google OAuth client for a Web application.
3. Add `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` to the environment used to run Django.
4. Add the authorized redirect URI `https://YOUR-DOMAIN/accounts/google/login/callback/` in the Google OAuth client. For local development, use `http://127.0.0.1:8000/accounts/google/login/callback/`.
5. Run `python manage.py migrate` and restart the application.

The Google option appears on the login and registration pages after both credential variables are present.
